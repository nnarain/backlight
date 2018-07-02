from neopixel import *
from Queue import Queue
from SimpleXMLRPCServer import SimpleXMLRPCServer
from threading import Thread
from argparse import ArgumentParser
import logging
import time


class BacklightDriver:
    LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
    LED_DMA        = 10      # DMA channel to use for generating signal (try 10)
    LED_BRIGHTNESS = 255     # Set to 0 for darkest and 255 for brightest
    LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
    LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

    CMD_ON   = 0
    CMD_OFF  = 1
    CMD_EXIT = 2

    def __init__(self, led_count, led_pin):
        self._led_count = led_count
        self._led_pin = led_pin

        # Create NeoPixel object with appropriate configuration.
        self._strip = Adafruit_NeoPixel(self._led_count, self._led_pin, self.LED_FREQ_HZ, self.LED_DMA, self.LED_INVERT, self.LED_BRIGHTNESS, self.LED_CHANNEL)
        # Intialize the library (must be called once before other functions).
        self._strip.begin()

        self._cmd_queue = Queue()

        self._animation_thread = None
    
    def start(self):
        self._animation_thread = Thread(target=self._animate)
        self._animation_thread.start()

    def stop(self):
        self.post_cmd(self.CMD_OFF)
        self.post_cmd(self.CMD_EXIT)
        if self._animation_thread:
            self._animation_thread.join()

    def _animate(self):
        running = True
        while True:
            if not self._cmd_queue.empty():
                cmd = self._cmd_queue.get(timeout=0.5)

                if cmd is not None:
                    if cmd == self.CMD_ON:
                        logging.info('Enabling animation')
                        running = True
                        pass
                    elif cmd == self.CMD_OFF:
                        logging.info('Disabling animation')
                        running = False
                        self.colorWipe(self._strip, Color(0,0,0), 10)
                        pass
                    elif cmd == self.CMD_EXIT:
                        logging.info('Exiting animation')
                        running = False
                        break

            if running:
                self.rainbowCycle(self._strip)

    def post_cmd(self, cmd):
        self._cmd_queue.put(cmd)

    @staticmethod
    def rainbowCycle(strip, wait_ms=20, iterations=5):
        """Draw rainbow that uniformly distributes itself across all pixels."""
        for j in range(256*iterations):
            for i in range(strip.numPixels()):
                strip.setPixelColor(i, BacklightDriver.wheel((int(i * 256 / strip.numPixels()) + j) & 255))
            strip.show()
            time.sleep(wait_ms/1000.0)

    # Define functions which animate LEDs in various ways.
    @staticmethod
    def colorWipe(strip, color, wait_ms=50):
        """Wipe color across display a pixel at a time."""
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, color)
            strip.show()
            time.sleep(wait_ms/1000.0)

    @staticmethod
    def wheel(pos):
        """Generate rainbow colors across 0-255 positions."""
        if pos < 85:
            return Color(pos * 3, 255 - pos * 3, 0)
        elif pos < 170:
            pos -= 85
            return Color(255 - pos * 3, 0, pos * 3)
        else:
            pos -= 170
            return Color(0, pos * 3, 255 - pos * 3)

class BacklightRpcServer:
    def __init__(self, config):
        self._backlight = BacklightDriver(config['led_count'], config['led_pin'])
        
        self._rpc_server = SimpleXMLRPCServer((config['host'], config['port']), allow_none=True)
        self._rpc_server.register_function(self._cmd_on, 'on')
        self._rpc_server.register_function(self._cmd_off, 'off')

        self._running = False

    def serve(self):
        self._running = True

        self._backlight.start()

        try:
            while self._running:
                self._rpc_server.handle_request()
        except KeyboardInterrupt:
            logging.info('Recieve keyboard interruption')

        self._backlight.stop()

    def _cmd_on(self):
        self._backlight.post_cmd(BacklightDriver.CMD_ON)

    def _cmd_off(self):
        self._backlight.post_cmd(BacklightDriver.CMD_OFF)

    def _cmd_exit(self):
        self._running = False

def main(args):
    args = vars(args)

    logging.info('Starting Backlight RPC Server')
    server = BacklightRpcServer(args)
    server.serve()

if __name__ == '__main__':

    logging.basicConfig(filename='backlight.log', level=logging.DEBUG)

    parser = ArgumentParser()
    parser.add_argument('-c', '--led-count', default=60, help='Number of LEDs on strip')
    parser.add_argument('-g', '--led-pin', default=18, help='LED strip GPIO pin')
    parser.add_argument('-i', '--host', default='0.0.0.0', help='RPC server interface')
    parser.add_argument('-p', '--port', default=6142, help='RPC server port')

    args = parser.parse_args()

    try:
        main(args)
    except Exception as e:
        logging.error('{}'.format(e))
 