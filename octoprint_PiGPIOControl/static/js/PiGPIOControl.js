/*
 * View model for Pi GPIO Control
 *
 * Author: Jorge Coelho
 * License: AGPLv3
 */
$(function() {
	function pigpiocontrolViewModel(parameters) {
		var self = this;
		console.log(self);
		self.dutycycle_percentages = [0, 25, 50, 75, 100];

		self.settingsViewModel = parameters[0];
		self.maxOutputId = 0;
		self.outputsUpdated = ko.observableArray();
		self.outputsStatus = ko.observableArray();

		self.onAllBound = function(allViewModels) {
			self.outputsUpdated(self.settingsViewModel.settings.plugins.PiGPIOControl.outputs.slice());
		}

		self.onSettingsShown = function() {
			self.outputsUpdated(self.settingsViewModel.settings.plugins.PiGPIOControl.outputs.slice());
		}

		self.onSettingsBeforeSave = function() {
			var outputsUpdated = self.outputsUpdated.slice();
			self.settingsViewModel.settings.plugins.PiGPIOControl.outputs(outputsUpdated);
		}

		// Outputs

		self.removeOutput = function (output) {
			self.outputsUpdated.remove(output);
		};

		self.cancelOutputSchedule = function(output) {
			$.ajax({
				url: window.PLUGIN_BASEURL + "PiGPIOControl/outputs/"+output["id"]+"/unscheduleShutdown",
				type: "POST",
				contentType: "application/json; charset=utf-8"
			}).fail(function(jqXHR, textStatus, errorThrown) {
				new PNotify({
					title: "PiGPIOControl",
					text: jqXHR.responseText,
					type: "error",
					hide: false
				});
			});
		}

		self.updateOutputsStatus = function(outputsStatus) {
			for (outputStatus in outputsStatus) {
				if (outputStatus["type"] == "PWM")
					outputStatus["status"]["updated_dutycycle"] = outputStatus["status"]["current_dutycycle"];
			}
			self.outputsStatus(outputsStatus);
		}


		// Simple output

		self.setOutputState = function(outputId, state) {
			$.ajax({
				url: window.PLUGIN_BASEURL + "PiGPIOControl/outputs/"+outputId+"/simple/" + state,
				type: "POST",
				contentType: "application/json; charset=utf-8"
			}).fail(function(jqXHR, textStatus, errorThrown) {
				new PNotify({
					title: "PiGPIOControl",
					text: jqXHR.responseText,
					type: "error",
					hide: false
				});
			});
		}

		self.turnOutputOn = function(output) {
			self.setOutputState(output["id"], "ON");
		}
		self.turnOutputOff = function(output) {
			self.setOutputState(output["id"], "OFF");
		}

		self.getRandomId = function () {
			  return Math.floor(Math.random() * (Number.MAX_SAFE_INTEGER/2));
		}


		self.addSimpleOutput = function () {
			self.outputsUpdated.push({
				id: ko.observable(self.getRandomId()),
				name: ko.observable("Name"),
				auto_startup: ko.observable(false),
				auto_shutdown: ko.observable(false),
				shutdown_on_failed: ko.observable(true),
				shutdown_delay: ko.observable(0),
				type: ko.observable("Simple"),
				config: {
					pin: ko.observable(0),
					active_mode: ko.observable("active_high"),
					default_state: ko.observable("OFF"),
				}
			});
		};

		// PWM output

		self.addPWMOutput = function () {
			self.outputsUpdated.push({
				id: ko.observable(self.getRandomId()),
				name: ko.observable("Name"),
				auto_startup: ko.observable(false),
				auto_shutdown: ko.observable(false),
				shutdown_on_failed: ko.observable(true),
				shutdown_delay: ko.observable(0),
				type: ko.observable("PWM"),
				config: {
					pin: ko.observable(0),
					frequency: ko.observable(1000),
					reverse: ko.observable(false),
					max_dutycycle: ko.observable(100),
					default_dutycycle: ko.observable(0)
				}
			});
		};

		self.setPWMdutycycle = function(output) {
			dutycycle_percentage = output["status"]["updated_dutycycle"];
			if (dutycycle_percentage == undefined)
				return;
			$.ajax({
				url: window.PLUGIN_BASEURL + "PiGPIOControl/outputs/"+output["id"]+"/pwm/" + dutycycle_percentage,
				type: "POST",
				contentType: "application/json; charset=utf-8"
			}).fail(function(jqXHR, textStatus, errorThrown) {
				new PNotify({
					title: "PiGPIOControl",
					text: jqXHR.responseText,
					type: "error",
					hide: false
				});
			});
		}


		self.requestAndUpdateStatus = function() {
			$.get({
				url: window.PLUGIN_BASEURL + "PiGPIOControl/outputs",
				dataType: "json"
			}).done(function(data) {
				self.updateOutputsStatus(data);
			});
		};

		const socketHandler = (message) => {
			const plugin = message.data.plugin
			if (plugin === "PiGPIOControl") {
				const type = message.data.data.type
				const content = message.data.data.content
				if (type === "pigpio_connection") {
					if (content.success) {
						new PNotify({
							title: "PiGPIOControl",
							text: "Successfully connected to pigpio daemon",
							type: "success",
							hide: true
						});
					} else {
						new PNotify({
							title: "PiGPIOControl",
							text: "Could not connect to pigpio daemon",
							type: "error",
							hide: false
						});
					}
				} else if (type === "output_status") {
					self.updateOutputsStatus(content);
				}
			}
		}
		OctoPrint.socket.onMessage("plugin", socketHandler)
		//self.requestAndUpdateStatus();
		ko.bindingHandlers.PiGPIOControl_timer = {
			update: function(element, valueAccessor) {
				var DateTime = luxon.DateTime;
				var datetimeISOstring = valueAccessor();

				var storedTimeout = $(element).data("timeout");
				if (storedTimeout)
					clearTimeout(storedTimeout);

				if (!datetimeISOstring) {
					ko.utils.setTextContent(element, "");
					return;
				}

				var countdownDateTime = DateTime.fromISO(datetimeISOstring);

				(function loop() {
					var now = DateTime.now();
					var remainingSeconds = countdownDateTime.diff(now, "seconds").toObject()["seconds"];
					if (remainingSeconds < 0) {
						ko.utils.setTextContent(element, "");
					} else {
						ko.utils.setTextContent(element, "Shutting down in " + Math.ceil(remainingSeconds) + "s");
						var timeout = setTimeout(loop, (remainingSeconds % 1) * 1000);
						$(element).data("timeout", timeout);
					}
				})();
			}
		}
	}

	/* view model class, parameters for constructor, container to bind to
	 * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
	 * and a full list of the available options.
	 */
	OCTOPRINT_VIEWMODELS.push({
		construct: pigpiocontrolViewModel,
		dependencies: [ "settingsViewModel" ],
		elements: ["#settings_plugin_PiGPIOControl", "#tab_plugin_PiGPIOControl", "#sidebar_plugin_PiGPIOControl"]
	});
});
