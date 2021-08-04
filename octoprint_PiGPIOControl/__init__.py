import octoprint.plugin
import octoprint.events
import pigpio
import copy
import flask
from .scheduler import Scheduler

class PiGPIOControlPlugin(
		octoprint.plugin.BlueprintPlugin,
		octoprint.plugin.StartupPlugin,
		octoprint.plugin.EventHandlerPlugin,
		octoprint.plugin.ShutdownPlugin,
		octoprint.plugin.SettingsPlugin,
		octoprint.plugin.AssetPlugin,
		octoprint.plugin.TemplatePlugin
	):

	def __init__(self):
		self.pi = None
		pigpio.exceptions = False

	# pigpio

	def connect_pipgio_daemon(self, send_message=False):
		pigpio_connection = self._settings.get(["pigpio_connection"], merged=True)
		hostname = pigpio_connection["hostname"]
		port = pigpio_connection["port"]


		self._logger.info(f'pigpio: Connecting ({hostname}:{port})')
		self.pi = pigpio.pi(hostname, port)
		if self.pi is not None and self.pi.connected:
			self._logger.info(f'pigpio: Successfully connected ({hostname}:{port})')
		else:
			self._logger.info(f'pigpio: Failed to connect ({hostname}:{port})')

		if send_message:
			self.send_message("pigpio_connection", {"success": self.pi.connected})

	def disconnect_pipgio_daemon(self):
		if self.pi is not None and self.pi.connected:
			self._logger.info("pigpio: Disconnecting")
			self.pi.stop()
		else:
			self._logger.info("pigpio: Already disconnected")

	# Outputs

	def outputs_print_started(self):
		outputs = self._settings.get(["outputs"])
		for output in outputs:
			auto_startup = output["auto_startup"]
			if auto_startup:
				if output["type"] == "Simple":
					self.simple_write_state(output, "ON")
				elif output["type"] == "PWM":
					self.pwm_write_dutycycle_percentage(output, 100)
		self.scheduler.unschedule_all()
		self.outputs_send_status()

	def outputs_print_stopped_successful(self):
		outputs = self._settings.get(["outputs"])
		for output in outputs:
			auto_shutdown = output["auto_shutdown"]
			if auto_shutdown:
				self.output_off_or_schedule_off(output)
		self.outputs_send_status()

	def outputs_print_stopped_fail(self):
		outputs = self._settings.get(["outputs"])
		for output in outputs:
			auto_shutdown = output["auto_shutdown"]
			shutdown_on_failed = output["shutdown_on_failed"]
			if auto_shutdown and shutdown_on_failed:
				self.output_off_or_schedule_off(output)
		self.outputs_send_status()

	def output_off_or_schedule_off(self, output):
		shutdown_delay = float(output["shutdown_delay"])
		if shutdown_delay == 0:
			self.simple_write_state(output, "OFF")
		else:
			self.scheduler.schedule_output(self.outputs_schedule_off, output, shutdown_delay, [output])

	def outputs_schedule_off(self, output):
		if output["type"] == "Simple":
			self.simple_write_state(output, "OFF")
		elif output["type"] == "PWM":
			self.pwm_write_dutycycle_percentage(output, 0)
		self.outputs_send_status()

	def outputs_set_default_state(self):
		outputs = self._settings.get(["outputs"])
		for output in outputs:
			if output["type"] == "Simple":
				state = output["config"]["default_state"]
				if state == "NONE":
					continue
				self.simple_write_state(output, state)
			elif output["type"] == "PWM":
				dutycycle_percentage = output["config"]["default_dutycycle"]
				self.pwm_write_dutycycle_percentage(output, dutycycle_percentage)

	def outputs_get_status(self):
		outputs = copy.deepcopy(self._settings.get(["outputs"]))
		outputs_schedule = None
		if hasattr(self, "scheduler"):
			outputs_schedule = self.scheduler.get_outputs_schedule()

		for output in outputs:
			if output["type"] == "Simple":
				output["status"] = self.simple_get_status(output)
			elif output["type"] == "PWM":
				output["status"] = self.pwm_get_status(output)

			if outputs_schedule is not None:
				try:
					output["status"]["timeout"] = outputs_schedule[output["id"]]["time"].isoformat()
				except KeyError:
					output["status"]["timeout"] = None
		return outputs

	def outputs_send_status(self):
		self.send_message("output_status", self.outputs_get_status())

	## Simple Output

	def simple_level_to_state(self, output_simple, level):
		if output_simple["config"]["active_mode"] == "active_low":
			return "OFF" if bool(level) else "ON"
		elif output_simple["config"]["active_mode"] == "active_high":
			return "ON" if bool(level) else "OFF"

	def simple_state_to_level(self, output_simple, state):
		if output_simple["config"]["active_mode"] == "active_low":
			if state == "ON":
				return 0
			else:
				return 1
		elif output_simple["config"]["active_mode"] == "active_high":
			if state == "ON":
				return 1
			else:
				return 0

	def simple_read_state(self, output_simple):
		if self.pi is None or not self.pi.connected:
			return "UNKNOWN"
		level = self.pi.read(int(output_simple["config"]["pin"]))
		if level < 0:
			raise Exception("Returned less than zero: " + str(level))
		return self.simple_level_to_state(output_simple, level)

	def simple_write_state(self, output_simple, state):
		if self.pi is None or not self.pi.connected:
			self._logger.warning(f'Failed to set output_simple {output_simple["id"]} to {state}')
			return
		pin = int(output_simple["config"]["pin"])
		level = self.simple_state_to_level(output_simple, state)
		res = self.pi.write(pin, level)
		if res < 0:
			raise Exception("Returned less than zero: " + str(res))
		self._logger.info(f'Wrote state/level {state}/{level} to pin {pin}')

	def simple_get_status(self, output_simple):
		output_status = {}
		output_status["current_state"] = self.simple_read_state(output_simple)
		return output_status

	## PWM Output
	def pwm_dutycycle_percentage_to_raw_dutycycle(self, output_pwm, dutycycle_percentage):
		dutycycle_percentage = max(0, min(100, dutycycle_percentage))
		if output_pwm["config"]["reverse"]:
			dutycycle_percentage = 100 - dutycycle_percentage

		pwm_range = self.pi.get_PWM_range(int(output_pwm["config"]["pin"]))

		max_dutycycle_percentage = max(1, min(100, int(output_pwm["config"]["max_dutycycle"])))
		pwm_range = round(pwm_range * (max_dutycycle_percentage/100))

		return max(0, min(pwm_range, round(pwm_range * (dutycycle_percentage/100))))

	def pwm_raw_dutycycle_to_dutycycle_percentage(self, output_pwm, raw_dutycycle):
		pwm_range = self.pi.get_PWM_range(int(output_pwm["config"]["pin"]))

		max_dutycycle_percentage = max(1, min(100, int(output_pwm["config"]["max_dutycycle"])))
		pwm_range = round(pwm_range * (max_dutycycle_percentage/100))

		dutycycle_percentage = max(0, min(100, round((raw_dutycycle*100)/pwm_range)))
		if output_pwm["config"]["reverse"]:
			dutycycle_percentage = 100 - dutycycle_percentage

		return dutycycle_percentage

	def pwm_read_dutycycle_percentage(self, output_pwm):
		if self.pi is None or not self.pi.connected:
			self._logger.warning(f'Failed to get output_pwm {output_pwm["id"]}')
			return
		pin = int(output_pwm["config"]["pin"])
		
		raw_dutycycle = self.pi.get_PWM_dutycycle(pin)
		if raw_dutycycle == -92:
			self.pwm_write_dutycycle_percentage(output_pwm, output_pwm["config"]["default_dutycycle"])
			raw_dutycycle = self.pi.get_PWM_dutycycle(pin)

		if raw_dutycycle < 0:
			raise Exception("Returned less than zero: " + str(raw_dutycycle))

			
		return self.pwm_raw_dutycycle_to_dutycycle_percentage(output_pwm, raw_dutycycle)

	def pwm_write_dutycycle_percentage(self, output_pwm, dutycycle_percentage):
		if self.pi is None or not self.pi.connected:
			self._logger.warning(f'Failed to set output_pwm {output_pwm["id"]} to {dutycycle_percentage}%')
			return
		pin = int(output_pwm["config"]["pin"])
		frequency = int(output_pwm["config"]["frequency"])
		
		res = self.pi.set_PWM_frequency(pin, frequency)
		if res < 0:
			raise Exception("Returned less than zero: " + str(res))
		raw_dutycycle = self.pwm_dutycycle_percentage_to_raw_dutycycle(output_pwm, dutycycle_percentage)
		res = self.pi.set_PWM_dutycycle(pin, raw_dutycycle)
		if res < 0:
			raise Exception("Returned less than zero: " + str(res))
		self._logger.info(f'Wrote percentage/raw_dutycycle {dutycycle_percentage}/{raw_dutycycle} to pin {pin}')

	def pwm_get_status(self, output_pwm):
		output_status = {}
		output_status["current_dutycycle"] = self.pwm_read_dutycycle_percentage(output_pwm)
		return output_status

	# Startup

	def on_after_startup(self):
		self.scheduler = scheduler.Scheduler(self._logger)
		self.scheduler.start()

	# Shutdown

	def on_shutdown(self):
		self.disconnect_pipgio_daemon()

	# Event Handler

	def on_event(self, event, payload):
		if event in (	octoprint.events.Events.CLIENT_OPENED,
						octoprint.events.Events.CLIENT_AUTHED,
						octoprint.events.Events.USER_LOGGED_IN):
			self.outputs_send_status()

		if event in (octoprint.events.Events.PRINT_STARTED):
			self.outputs_print_started()

		if event in (octoprint.events.Events.PRINT_DONE):
			self._logger.info("Event: " + event)
			self.outputs_print_stopped_successful()

		if event in (octoprint.events.Events.PRINT_CANCELLED, octoprint.events.Events.PRINT_FAILED):
			self._logger.info("Event: " + event)
			self.outputs_print_stopped_fail()



	# Settings

	def on_settings_initialized(self):
		self.connect_pipgio_daemon()
		self.outputs_set_default_state()

	def get_settings_defaults(self):
		return {
				"pigpio_connection": {
					"hostname": "localhost",
					"port": 8888
				},
				"outputs": [ ]
		}

	def on_settings_save(self, data):
		old_pigpio_connection = self._settings.get(["pigpio_connection"], merged=True)
		old_outputs = self._settings.get(["outputs"])

		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		new_pigpio_connection = self._settings.get(["pigpio_connection"], merged=True)
		new_outputs = self._settings.get(["outputs"])

		if not old_pigpio_connection == new_pigpio_connection:
			self.disconnect_pipgio_daemon()
			self.connect_pipgio_daemon(send_message=True)

		old_outputs_ids = [output["id"] for output in old_outputs]
		new_outputs_ids = [output["id"] for output in new_outputs]
		removed_outputs_id = list(set(old_outputs_ids) - set(new_outputs_ids))
		for output_id in removed_outputs_id:
			self.scheduler.unschedule_output_id(output_id)

		self.outputs_send_status()


	# Template

	def get_template_configs(self):
		return [{"type": "settings", "custom_bindings":True},
				{"type": "sidebar", "custom_bindings":True, "icon": "bolt"}]

	# Assets

	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return {
			"js": ["js/PiGPIOControl.js", "js/lib/luxon.js"],
			"css": ["css/PiGPIOControl.css"],
			"less": ["less/PiGPIOControl.less"]
		}

	# Blueprint

	@octoprint.plugin.BlueprintPlugin.route("/outputs", methods=["GET"])
	def blueprint_get_outputs_state(self):
		return flask.jsonify(self.outputs_get_status())

	@octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>/unscheduleShutdown", methods=["POST"])
	def blueprint_unschedule_output_shutdown(self, output_id):
		if "application/json" not in flask.request.headers["Content-Type"]:
			return flask.make_response("expected json", 400)

		outputs = self._settings.get(["outputs"])

		output = next((output for output in outputs if output["id"] == output_id), None)

		if output is None:
			return flask.make_response("malformed request1", 400)

		self.scheduler.unschedule_output(output);

		self.outputs_send_status()
		return flask.make_response('', 204)

	@octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>/simple/<string:state>", methods=["POST"])
	def blueprint_set_simple_output_state(self, output_id, state):
		if "application/json" not in flask.request.headers["Content-Type"]:
			return flask.make_response("expected json", 400)
		if not state == "ON" and not state == "OFF":
			return flask.make_response("malformed request (state)", 400)

		outputs = self._settings.get(["outputs"])

		output = next((output for output in outputs if output["id"] == output_id and output["type"] == "Simple"), None)

		if output is None:
			return flask.make_response("malformed request (output)", 400)

		self.simple_write_state(output, state)
		self.outputs_send_status()
		return flask.make_response('', 204)

	@octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>/pwm/<int:dutycycle_percentage>", methods=["POST"])
	def blueprint_set_pwm_output_state(self, output_id, dutycycle_percentage):
		if "application/json" not in flask.request.headers["Content-Type"]:
			return flask.make_response("expected json", 400)

		outputs = self._settings.get(["outputs"])

		output = next((output for output in outputs if output["id"] == output_id and output["type"] == "PWM"), None)

		if output is None:
			return flask.make_response("malformed request2", 400)

		self.pwm_write_dutycycle_percentage(output, dutycycle_percentage)
		self.outputs_send_status()
		return flask.make_response('', 204)

	# Socket

	def send_message(self, msg_type, content):
		self._plugin_manager.send_plugin_message("PiGPIOControl", {"type": msg_type, "content": content})

	# Hooks

	def get_update_information(self, *args, **kwargs):
		return dict(
			pigpio_control=dict(
				displayName=self._plugin_name,
				displayVersion=self._plugin_version,
	
				type="github_commit",
				current=self._plugin_version,
				user="JorgeGCoelho",
				repo="Octoprint-PiGPIOControl",
	
				pip="https://github.com/JorgeGCoelho/Octoprint-PiGPIOControl/archive/{target}.zip"
			)
		)

__plugin_name__ = "PiGPIOControl"

__plugin_pythoncompat__ = ">=3,<4" # only python 3

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = PiGPIOControlPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}

