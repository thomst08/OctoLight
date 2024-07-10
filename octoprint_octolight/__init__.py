# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import math

import flask
import octoprint.plugin
import RPi.GPIO as GPIO
from flask_babel import gettext
from octoprint.access.permissions import Permissions
from octoprint.events import Events
from octoprint.util import RepeatedTimer

GPIO.setwarnings(False)
if(GPIO.getmode() == None):
	GPIO.setmode(GPIO.BOARD)


class OctoLightPlugin(
	octoprint.plugin.AssetPlugin,
	octoprint.plugin.StartupPlugin,
	octoprint.plugin.TemplatePlugin,
	octoprint.plugin.SimpleApiPlugin,
	octoprint.plugin.SettingsPlugin,
	octoprint.plugin.EventHandlerPlugin,
	octoprint.plugin.RestartNeedingPlugin
):

	# Event types
	event_options = [
		{"name": "Nothing", "value": "na"},
		{"name": "Turn Light On", "value": "on"},
		{"name": "Turn Light Off", "value": "off"},
		{"name": "Delay Turn Light Off", "value": "delay"}
	]

	# Monitor events
	monitored_events = [
		{"label": "Printer Start:", "settingName": "event_printer_start"},
		{"label": "Printer Done:", "settingName": "event_printer_done"},
		{"label": "Printer Failed:", "settingName": "event_printer_failed"},
		{"label": "Printer Cancelled:", "settingName": "event_printer_cancelled"},
		{"label": "Printer Paused:", "settingName": "event_printer_paused"},
		{"label": "Printer Error:", "settingName": "event_printer_error"},
		{"label": "OctoPrint Start:", "settingName": "event_octoprint_start"},
		{"label": "OctoPrint Stop:", "settingName": "event_octoprint_stop"},
	]

	#Default/Variables for plugin to function
	light_state=False
	delayed_state=None
	light_pin=13
	inverted_output=False
	delayed_off_time=5
	button_pin=15
	button_enabled=False
	button_high=False
	toggle_output=False
	toggle_delay=200


	# Function to setup default settings
	def get_settings_defaults(self):
		return dict(
			light_pin=13,
			inverted_output=False,
			toggle_output=False,
			toggle_delay=200,
			delay_off=5,

			button_pin=15,
			button_enabled=False,
			button_high=False,

			bcm_mode=GPIO.getmode() == GPIO.BCM,

			#Setup the default value for each event
			event_printer_start=self.event_options[0]["value"],
			event_printer_done=self.event_options[0]["value"],
			event_printer_failed=self.event_options[0]["value"],
			event_printer_cancelled=self.event_options[0]["value"],
			event_printer_paused=self.event_options[0]["value"],
			event_printer_error=self.event_options[0]["value"],
			event_octoprint_start=self.event_options[0]["value"],
			event_octoprint_stop=self.event_options[0]["value"],

			#Setup the default vales for custom GCode
			enable_custom_gcode=False,
			custom_gcode_on="OCTOLIGHT ON",
			custom_gcode_off="OCTOLIGHT OFF",
			custom_gcode_delay_off="OCTOLIGHT DELAY OFF"
		)

	def get_template_configs(self):
		return [
			dict(type="navbar", custom_bindings=True),
			dict(type="settings", custom_bindings=True)
		]

	def get_assets(self):
		# Define your plugin's asset files to automatically include in the
		# core UI here.
		return dict(
			js=["js/octolight.js"],
			css=["css/octolight.css"],
			#less=["less/octolight.less"]
		)

	def get_template_vars(self):
		return {
			"event_options": self.event_options,
			"monitored_events": self.monitored_events
		}
	
	# Handles the resettinng of previous settings and reloads plugin settings
	def reset_and_reload(self):
		self._logger.debug("OctoLight Settings updated, resetting")
		self.light_off()
		GPIO.cleanup(self.light_pin)
		if self.button_enabled:
			GPIO.remove_event_detect(self.button_pin)
			GPIO.cleanup(self.button_pin)

		self.on_after_startup()

	# Handles the setup of the plugin and setups up pins
	def on_after_startup(self):
		# Load all the settings into plugin variables
		self.light_state = False
		self.light_pin = int(self._settings.get(["light_pin"]))
		self.inverted_output = bool(self._settings.get(["inverted_output"]))
		self.delayed_off_time = int(self._settings.get(["delay_off"]))

		self.toggle_output = bool(self._settings.get(["toggle_output"]))
		self.toggle_delay = float(self._settings.get(["toggle_delay"]))

		self.button_pin = int(self._settings.get(["button_pin"]))
		self.button_enabled = bool(self._settings.get(["button_enabled"]))
		self.button_high = bool(self._settings.get(["button_high"]))

		# Debugging settings
		self._logger.debug ("--------------------------------------------")
		self._logger.debug ("OctoLight started, listening for GET request")
		self._logger.debug (
			"Light pin: {}, inverted_input: {}, Delay Time: {}".format(
				self.light_state,
				self.inverted_output,
				self.delayed_off_time
			)
		)
		self._logger.debug ("OctoLight button")
		self._logger.debug (
			"button_pin: {}, button_enabled: {}, button_high: {}".format(
				self.button_pin,
				self.button_enabled,
				self.button_high
			)
		)
		self._logger.debug ("--------------------------------------------")

		# Setting the default state of pin
		GPIO.setup(self.light_pin, GPIO.OUT)
		if self.inverted_output:
			GPIO.output(self.light_pin, GPIO.HIGH)
		else:
			GPIO.output(self.light_pin, GPIO.LOW)

		# Process the "OctoPrint Start" event here. Because this event happens
		# before on_after_startup() is called, the GPIO won't be set up yet
		# and thus it simply won't work if processed by on_event().
		self.trigger_event(self._settings.get(["event_octoprint_start"])[0])

		self._plugin_manager.send_plugin_message(
			self._identifier, dict(isLightOn=self.light_state)
		)
		self.setup_button()


	# Handles the setup of a button if enabled
	def setup_button(self):
		if self.button_enabled:
			self._logger.debug("Button Enabled")

			# Check if the pin is in a high or a low state and sets up to detect the button press
			if self.button_high:
				GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
				gpio_event=GPIO.RISING
			else:
				GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
				gpio_event=GPIO.FALLING
			
			# Remove any detections and then setup a function to detect events
			GPIO.remove_event_detect(self.button_pin)
			GPIO.add_event_detect(
				self.button_pin,
				gpio_event,
				callback=self.button_press_trigger,
				bouncetime=200
			)
		else:
			self._logger.debug("Button Disabled")


	def button_press_trigger(self, _):
		self.light_toggle()


	def light_button_toggle(self):
		GPIO.output(self.light_pin, GPIO.LOW)
		self.delayed_toggle.cancel()
		self.delayed_toggle = None


	def light_toggle(self):
		# Sets the GPIO every time, if user changed it in the settings.
		GPIO.setup(self.light_pin, GPIO.OUT)

		self.light_state = not self.light_state
		self.stopTimer()

		# Handles a toggle on and off as a button press
		if self.toggle_output:
			GPIO.output(self.light_pin, GPIO.HIGH)
			self.delayed_toggle=RepeatedTimer(self.toggle_delay / 1000, self.light_button_toggle)
			self.delayed_toggle.start()
		# Sets the light state depending on the inverted output setting (XOR)
		elif self.light_state ^ self.inverted_output:
			GPIO.output(self.light_pin, GPIO.HIGH)
		else:
			GPIO.output(self.light_pin, GPIO.LOW)

		self._logger.debug("Got request. Light state: {}".format(self.light_state))

		self._plugin_manager.send_plugin_message(
			self._identifier, dict(isLightOn=self.light_state)
		)

	def light_on(self):
		if not self.light_state:
			self.light_toggle()

	def light_off(self):
		self.stopTimer()
		if self.light_state:
			self.light_toggle()


	# Handle GET requests, return the state of the light
	@Permissions.PLUGIN_OCTOLIGHT_STATUS.require(403)
	def on_api_get(self, request):
		#-------------------
		# Old actions these will be removed in the future and should not be used.
		action = request.args.get("action", default="", type=str)
		delay = request.args.get("delay", default=self.delayed_off_time, type=int)

		if action != "":
			self._logger.warning("OctoLight API GET calls to change the light are soon to be removed, please change to the updated POST API calls")

		if action == "toggle":
			self.light_toggle()
		elif action == "turnOn":
			self.light_on()
		elif action == "turnOff":
			self.light_off()
		elif action == "delayOff":
			self.delayed_off_setup(delay)
		elif action == "delayOffStop":
			self.delayed_off()
		# End of old actions
		#-------------------

		return flask.jsonify(state=self.light_state)

	# Setups up required commands and data for POST request
	def get_api_commands(self):
		return dict(
			toggle=[],
			turnOn=[],
			turnOff=[],
			delayOff=[],	# "delay" is an optional value to send and must be a number greater then 0
			delayOffStop=[]
			)

	# Handles POST commands, this is used to handle the changing of the lights state
	# based on the command issued
	@Permissions.PLUGIN_OCTOLIGHT_CONTROL.require(403)
	def on_api_command(self, command, data):
		if command == "toggle":
			self.light_toggle()
		elif command == "turnOn":
			self.light_on()
		elif command == "turnOff":
			self.light_off()
		#Turn on light and setup timer
		elif command == "delayOff":
			if "delay" in data:
				if not isinstance(data["delay"], int):
					return flask.make_response("Bad delay value", 400)
				elif data["delay"] < 0:
					return flask.make_response("Bad delay value", 400)
				self.delayed_off_setup(data["delay"])
			else:
				self.delayed_off_setup(self.delayed_off_time)
		#Turn off off timer and light
		elif command == "delayOffStop":
			self.delayed_off()
		else:
			return flask.make_response("Unknown command", 400)
		return flask.jsonify(state=self.light_state)
	

	#This stops the current timer, this does not control the light
	def stopTimer(self):
		if self.delayed_state is not None:
			self._logger.debug("Stopping schedule")
			self.delayed_state.cancel()
			self.delayed_state = None

		return

	#This sets up the timer, this does not control the light
	#Check if the timer is already running, if so, stop it, then set it up with a new time
	def startTimer(self, mins):
		if math.isnan(int(mins)):
			self._logger.error(
				"Error: Received value that is not an int: {}".format(mins)
			)
			return
		
		self.stopTimer()

		self._logger.debug("Setting up schedule")
		self.delayed_state = RepeatedTimer(int(mins) * 60, self.delayed_off)
		self.delayed_state.start()
		self._logger.debug("Time till shutoff: {} seconds".format(int(mins) * 60))

		return

	#Setup the light to shutoff when called
	def delayed_off(self):
		self.light_off()
		self.stopTimer()
		return

	#Setup the light to turn on then off after a set time
	def delayed_off_setup(self, mins):
		#Make sure a value was sent
		if math.isnan(int(mins)):
			self._logger.error("Error: Received value that is not an int: {}".format(mins))
			return
		
		#Stop any past timers
		self.delayed_off()

		self.light_on()
		self.startTimer(mins)
		return

	# Handles events form OctoPrint
	def on_event(self, event, payload):
		if event == Events.CLIENT_OPENED:
			self._plugin_manager.send_plugin_message(
				self._identifier, dict(isLightOn=self.light_state)
			)
			return
		if event == Events.PRINT_STARTED:
			self.trigger_event(self._settings.get(["event_printer_start"])[0])
			return
		if event == Events.PRINT_DONE:
			self.trigger_event(self._settings.get(["event_printer_done"])[0])
			return
		if event == Events.PRINT_FAILED:
			self.trigger_event(self._settings.get(["event_printer_failed"])[0])
			return
		if event == Events.PRINT_CANCELLED:
			self.trigger_event(self._settings.get(["event_printer_cancelled"])[0])
			return
		if event == Events.PRINT_PAUSED:
			self.trigger_event(self._settings.get(["event_printer_paused"])[0])
			return
		if event == Events.ERROR:
			self.trigger_event(self._settings.get(["event_printer_error"])[0])
			return
		# Events.STARTUP is handled in on_after_startup()
		if event == Events.SHUTDOWN:
			self.trigger_event(self._settings.get(["event_octoprint_stop"])[0])
			return
		if event == Events.SETTINGS_UPDATED:
			self.reset_and_reload()

	#Handles the event that should happen
	def trigger_event(self, user_setting):
		if user_setting == "on":
			self.light_on()
		elif user_setting == "off":
			self.light_off()
		elif user_setting == "delay":
			self.delayed_off_setup(self.delayed_off_time)
		else:
			self._logger.warning(
				"Unknown event trigger, received: {}".format(user_setting)
			)

		return
	
	#Handles when gcode is sent to the print, used to detect custom gcode if enabled
	def gcode_trigger_event(self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None, *args, **kwargs):
		if not self._settings.get(["enable_custom_gcode"]):
			return

		if cmd == self._settings.get(["custom_gcode_on"]):
			self._logger.debug("OctoLight Received custom code: on")
			self.light_on()
		elif cmd == self._settings.get(["custom_gcode_off"]):
			self._logger.debug("OctoLight Received custom code: off")
			self.light_off()
		if cmd == self._settings.get(["custom_gcode_delay_off"]):
			self._logger.debug("OctoLight Received custom code: delay off")
			self.delayed_off_setup(self.delayed_off_time)
		
		return


	def get_additional_permissions(self, *args, **kwargs):
		return [
				dict(key="CONTROL",
					name="Control",
					description=gettext("Allows switching relays on/off"),
					roles=["admin"],
					dangerous=True,
					default_groups=[Permissions.ADMIN_GROUP]),
				dict(key="STATUS",
					name="Status",
					description=gettext("Allows the viewing of Light status"),
					roles=["admin"],
					dangerous=True,
					default_groups=[Permissions.ADMIN_GROUP])
				]


	def get_update_information(self):
		return dict(
			octolight=dict(
				displayName="OctoLight",
				displayVersion=self._plugin_version,
				type="github_release",
				current=self._plugin_version,
				user="thomst08",
				repo="OctoLight",
				pip="https://github.com/thomst08/OctoLight/archive/{target}.zip"
			)
		)

__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = OctoLightPlugin()

__plugin_hooks__ = {
	"octoprint.plugin.softwareupdate.check_config":
	__plugin_implementation__.get_update_information,
	"octoprint.comm.protocol.gcode.sent": __plugin_implementation__.gcode_trigger_event,
	"octoprint.access.permissions": __plugin_implementation__.get_additional_permissions
}
