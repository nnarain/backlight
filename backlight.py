import time
import json
import logging
from neopixel import *
from queue import Queue
from threading import Thread
import paho.mqtt.client as mqtt

from argparse import ArgumentParser


class BacklightDriver:
    LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
    LED_DMA        = 10      # DMA channel to use for generating signal (try 10)
    LED_BRIGHTNESS = 255     # Set to 0 for darkest and 255 for brightest
    LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
    LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

    CMD_ON   = 0
    CMD_OFF  = 1
    CMD_EXIT = 2
    CMD_RAINBOW = 3
    CMD_SOLID =  4
    CMD_CLEAR = 5

    KEY_STATE = 'state'
    KEY_EFFECT = 'effect'
    KEY_COLOR = 'color'
    STATE_ON = 'ON'
    STATE_OFF = 'OFF'

    VALID_EFFECTS = ['rainbow', 'solid']

    def __init__(self, led_count, led_pin):
        self._led_count = led_count
        self._led_pin = led_pin

        self._state = {}
        self._state_callback = None

        self._update_state(self.KEY_STATE, self.STATE_OFF)
        self._update_state(self.KEY_EFFECT, self.VALID_EFFECTS[0])

        # Create NeoPixel object with appropriate configuration.
        self._strip = Adafruit_NeoPixel(self._led_count, self._led_pin, self.LED_FREQ_HZ, self.LED_DMA, self.LED_INVERT, self.LED_BRIGHTNESS, self.LED_CHANNEL)
        # Intialize the library (must be called once before other functions).
        self._strip.begin()

        self._cmd_queue = Queue()

        self._animation_thread = None
        self._animation_running = False

        self._is_on = False
        self._solid_color = Color(255, 0, 0)

    def start(self):
        self._animation_thread = Thread(target=self._animate)
        self._animation_running = True
        self._animation_thread.start()

        self._is_on = True
        self._update_state(self.KEY_STATE, self.STATE_ON)

    def stop(self):
        self.turn_off()
        self._animation_running = False
        if self._animation_thread:
            self._animation_thread.join()

        self._update_state(self.KEY_STATE, self.STATE_OFF)

    def _animate(self):
        while self._animation_running:
            if not self._cmd_queue.empty():
                (cmd, args) = self._cmd_queue.get(timeout=0.5)

                if cmd is not None:
                    if cmd == self.CMD_ON:
                        self.turn_on()
                    elif cmd == self.CMD_OFF:
                        self.turn_off()
                    elif cmd == self.CMD_CLEAR:
                        self._colorWipe(Color(0,0,0), wait_ms=args)

            if self._is_on:
                if self._state[self.KEY_EFFECT] == 'rainbow':
                    self._rainbowCycle()
                elif self._state[self.KEY_EFFECT] == 'solid':
                    self._colorWipe(self._solid_color)

    def turn_on(self):
        logging.info('Backlight on')
        self._is_on = True
        self._update_state(self.KEY_STATE, self.STATE_ON)

    def turn_off(self, ms=50):
        logging.info('Backlight off')
        self._is_on = False
        self._update_state(self.KEY_STATE, self.STATE_OFF)

        self._cmd_queue.put((self.CMD_CLEAR, ms))

    def set_effect(self, effect, args=None):
        if effect not in self.VALID_EFFECTS:
            logging.warn('Invalid effect provided: {}'.format(effect))
            return

        self._update_state(self.KEY_EFFECT, effect)
        self._is_on = False
        self._cmd_queue.put((self.CMD_ON, None))

    def set_solid_color(self, color):
        logging.info('Setting color to {}'.format(color))
        self._solid_color = Color(color['g'], color['r'], color['b'])

        self._update_state(self.KEY_COLOR, color)

    def set_state_callback(self, callback):
        self._state_callback = callback

    def _update_state(self, k, v):
        self._state[k] = v

        if self._state_callback:
            self._state_callback(self._state)

    def _rainbowCycle(self, wait_ms=20, iterations=5):
        """Draw rainbow that uniformly distributes itself across all pixels."""
        for j in range(256*iterations):
            for i in range(self._strip.numPixels()):
                self._strip.setPixelColor(i, self._wheel((int(i * 256 / self._strip.numPixels()) + j) & 255))

                if not self._is_on:
                    return

            self._strip.show()
            time.sleep(wait_ms/1000.0)

    # Define functions which animate LEDs in various ways.
    def _colorWipe(self, color, wait_ms=50):
        """Wipe color across display a pixel at a time."""
        for i in range(self._strip.numPixels()):
            self._strip.setPixelColor(i, color)
            self._strip.show()
            time.sleep(wait_ms/1000.0)

    @staticmethod
    def _wheel(pos):
        """Generate rainbow colors across 0-255 positions."""
        if pos < 85:
            return Color(pos * 3, 255 - pos * 3, 0)
        elif pos < 170:
            pos -= 85
            return Color(255 - pos * 3, 0, pos * 3)
        else:
            pos -= 170
            return Color(0, pos * 3, 255 - pos * 3)

class BacklightMqttClient(object):
    COMMAND_TOPIC = '/home/backlight/set'
    STATE_TOPIC = '/home/backlight/state'

    def __init__(self, backlight):
        self._backlight = backlight
        self._backlight.set_state_callback(self._send_state)

        # setup MQTT client
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._topic_to_callback = {}

        self.register(self.COMMAND_TOPIC, self._on_command)

        # start the backlight
        self._backlight.start()

    def _on_command(self, command):
        if 'state' in command:
            state = command['state']
            if state == 'ON':
                self._backlight.turn_on()
            elif state == 'OFF':
                self._backlight.turn_off()
        
        if 'effect' in command:
            effect = command['effect']
            self._backlight.set_effect(effect)

        if 'color' in command:
            color = command['color']
            self._backlight.set_solid_color(color)

    def _send_state(self, state):
        logging.info('Publishing state: {}'.format(state))
        self._client.publish(self.STATE_TOPIC, json.dumps(state))

    def _on_connect(self, client, userdata, flags, rc):
        logging.info('MQTT client connected')
        # subscribe to registered topics
        for topic in self._topic_to_callback.keys():
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        logging.info('Message recieved on topic "{}" with data: {}'.format(msg.topic, msg.payload))
        # get callback for this topic and call it, if it exists
        callback = self._topic_to_callback.get(msg.topic, None)

        if callback:
            payload = msg.payload.decode('utf-8')
            try:
                json_data = json.loads(payload)
                callback(json_data)
            except ValueError as e:
                logging.error('Caught ValueError: {}'.format(e))
            except TypeError as e:
                logging.error('Caught TypeError: {}'.format(e))
            except Exception as e:
                logging.error('Caught unknown exception: {}'.format(e))

    def connect(self, broker):
        logging.info('Connecting to MQTT broker "{}"'.format(broker))
        self._client.connect(broker)

    def spin(self):
        self._client.loop_forever()

    def register(self, topic, callback):
        self._topic_to_callback[topic] = callback


def main(args):
    port = args.port
    led_count = args.led_count
    led_pin = args.led_pin

    # create the driver
    backlight = BacklightDriver(led_count, led_pin)

    # create the mqtt client
    client = BacklightMqttClient(backlight)
    client.connect('localhost')

    # loop
    try:
        client.spin()
    except KeyboardInterrupt:
        pass

    backlight.stop()

    logging.info('Exited')


if __name__ == '__main__':
    logging.basicConfig(format="[%(levelname)-8s] %(filename)s:%(lineno)d: %(message)s", filename='backlight.log', level=logging.DEBUG)

    parser = ArgumentParser()
    parser.add_argument('-c', '--led-count', default=60, help='Number of LEDs on strip')
    parser.add_argument('-g', '--led-pin', default=18, help='LED strip GPIO pin')
    parser.add_argument('-p', '--port', default=6142, help='RPC server port')

    args = parser.parse_args()

    try:
        main(args)
    except Exception as e:
        import traceback
        logging.error('{}'.format(e))
        traceback.print_exc()