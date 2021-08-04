import sched
import time
import datetime
import threading

class Scheduler(threading.Thread):
	def __init__(self, logger):
		super().__init__(daemon=True)
		self.logger = logger.getChild("scheduler")
		self.logger.info("scheduler thread")
		self.condition = threading.Condition()

	def run(self):
		self.scheduler = sched.scheduler(timefunc=time.monotonic, delayfunc=time.sleep)
		while True:
			self.logger.info("Running")
			delay_time = self.scheduler.run(blocking=False)
			with self.condition:
				self.logger.info("Waiting " + str(delay_time))
				self.condition.wait(timeout=delay_time)

	def schedule_action(self, data, action, arguments):
		action(*arguments)

	def schedule_output(self, action, output, delay, arguments=()):
		self.unschedule_output(output)

		data = output
		self.logger.info("Scheduled output id " + str(data["id"]))
		self.scheduler.enter(delay, 100, self.schedule_action, (data, action, arguments))
		with self.condition:
			self.condition.notify_all()

	def unschedule_output(self, output):
		return self.unschedule_output_id(output["id"])

	def unschedule_output_id(self, output_id):
		with self.condition:
			output_queue = [event for event in self.scheduler.queue if event[3][0]["id"] == output_id]
			for event in output_queue:
				try:
					self.scheduler.cancel(event)
					self.logger.info("Unscheduled output id " + str(event[3][0]["id"]))
				except e:
					self.logger.error("Failed to cancel schedule for output with id " +str(event[3][0]["id"]), exc_info=True)
				self.condition.notify_all()

	def unschedule_all(self):
		with self.condition:
			self.logger.info("Unscheduling all")
			for event in self.scheduler.queue:
				try:
					self.scheduler.cancel(event)
				except e:
					self.logger.error("Failed to cancel schedule for output with id " +str(event[3][0]["id"]), exc_info=True)
				self.condition.notify_all()

	def get_outputs_schedule(self):
		outputs_schedule = {}
		current_datetime = datetime.datetime.now(tz=datetime.timezone.utc)
		current_monotonic_time = time.monotonic()
		for event in self.scheduler.queue:
			output = event[3][0]
			delay = event[0] - current_monotonic_time
			delta = datetime.timedelta(seconds=delay)
			outputs_schedule[output["id"]] = {"time": current_datetime + delta}
		return outputs_schedule

