import asyncio
import socket
import logging
import time

_LOGGER = logging.getLogger(__name__)

CMD_MAIN = "Main"
CMD_BRIGHTNESS = "Main.Brightness"
CMD_BASS_EQ = "Main.Bass"
CMD_CONTROL_STANDBY = "Main.ControlStandby"
CMD_AUTO_STANDBY = "Main.AutoStandby"
CMD_VERSION = "Main.Version"
CMD_MUTE = "Main.Mute"
CMD_POWER = "Main.Power"
CMD_AUTO_SENSE = "Main.AutoSense"
CMD_SOURCE = "Main.Source"
CMD_VOLUME = "Main.Volume"

MSG_ON = 'On'
MSG_OFF = 'Off'

C338_CMDS = {
    'Main':
        {'supported_operators': ['?']
         },
    'Main.AnalogGain':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(0, 0),
         'type': int
         },
    'Main.Brightness':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(0, 4),
         'type': int
         },
    'Main.Mute':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.Power':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.Volume':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': range(-80, 0),
         'type': float
         },
    'Main.Bass':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.ControlStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.AutoStandby':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.AutoSense':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': [MSG_OFF, MSG_ON],
         'type': bool
         },
    'Main.Source':
        {'supported_operators': ['+', '-', '=', '?'],
         'values': ["Stream", "Wireless", "TV", "Phono", "Coax1", "Coax2",
                    "Opt1", "Opt2"]
         },
    'Main.Version':
        {'supported_operators': ['?'],
         'type': float
         },
    'Main.Model':
        {'supported_operators': ['?'],
         'values': ['NADC338']
         }
}


class NADReceiverTCPC338(asyncio.Protocol):
    PORT = 30001

    CMD_MIN_INTERVAL = 0.15

    def __init__(self, host, loop, state_changed_cb=None,
                 reconnect_interval=15, connect_timeout=10):
        self._loop = loop
        self._host = host
        self._state_changed_cb = state_changed_cb
        self._reconnect_interval = reconnect_interval
        self._connect_timeout = connect_timeout

        self._transport = None
        self._buffer = ''
        self._last_cmd_time = 0

        self._closing = False
        self._state = {}

    @staticmethod
    def make_command(command, operator, value=None):
        cmd_desc = C338_CMDS[command]
        # validate operator
        if operator in cmd_desc['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError("No value provided")
            elif operator in ['?', '-', '+'] and value is not None:
                raise ValueError(
                    "Operator \'%s\' cannot be called with a value" % operator)

            if value is None:
                cmd = command + operator
            else:
                # validate value
                if 'values' in cmd_desc:
                    if 'type' in cmd_desc and cmd_desc['type'] == bool:
                        value = cmd_desc['values'][int(value)]
                    elif value not in cmd_desc['values']:
                        raise ValueError("Given value \'%s\' is not one of %s"
                                         % (value, cmd_desc['values']))

                cmd = command + operator + str(value)
        else:
            raise ValueError("Invalid operator provided %s" % operator)

        return cmd

    @staticmethod
    def parse_part(response):
        key, value = response.split('=')

        cmd_desc = C338_CMDS[key]

        # convert the data to the correct type
        if 'type' in cmd_desc:
            if cmd_desc['type'] == bool:
                value = bool(cmd_desc['values'].index(value))
            else:
                value = cmd_desc['type'](value)

        return key, value

    def connection_made(self, transport):
        self._transport = transport

        sock = self._transport.get_extra_info('socket')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 1)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 3)

        _LOGGER.debug("Connected to %s", self._host)
        self._loop.create_task(self.exec_command('Main', '?'))

    def data_received(self, data):
        data = data.decode('utf-8').replace('\x00', '')

        self._buffer += data

        new_state = {}
        while '\r\n' in self._buffer:
            line, self._buffer = self._buffer.split('\r\n', 1)
            key, value = self.parse_part(line)
            new_state[key] = value

            # volume changes implicitly disables mute,
            if key == 'Main.Volume' and self._state.get('Main.Mute') is True:
                new_state['Main.Mute'] = False

        if new_state:
            _LOGGER.debug("state changed %s", new_state)
            self._state.update(new_state)
            if self._state_changed_cb:
                self._state_changed_cb(self._state)

    def connection_lost(self, exc):
        if exc:
            _LOGGER.error("Disconnected from %s because of %s", self._host, exc)
        else:
            _LOGGER.debug("Disconnected from %s because of close/abort.",
                          self._host)
        self._transport = None

        self._state.clear()
        if self._state_changed_cb:
            self._state_changed_cb(self._state)

        if not self._closing:
            self._loop.create_task(self.connect())

    async def connect(self):
        self._closing = False

        while not self._closing and not self._transport:
            try:
                _LOGGER.debug("Connecting to %s", self._host)
                connection = self._loop.create_connection(
                    lambda: self, self._host, NADReceiverTCPC338.PORT)
                await asyncio.wait_for(
                    connection, timeout=self._connect_timeout)
                return
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
                _LOGGER.exception("Error connecting to %s, reconnecting in %ss",
                                  self._host, self._reconnect_interval,
                                  exc_info=True)
                await asyncio.sleep(self._reconnect_interval, loop=self._loop)

    async def disconnect(self):
        self._closing = True
        if self._transport:
            self._transport.close()

    async def exec_command(self, command, operator, value=None):
        if self._transport:
            # throttle commands to CMD_MIN_INTERVAL
            cmd_wait_time = (self._last_cmd_time
                             + NADReceiverTCPC338.CMD_MIN_INTERVAL) - time.time()
            if cmd_wait_time > 0:
                await asyncio.sleep(cmd_wait_time)
            cmd = self.make_command(command, operator, value)
            self._transport.write(cmd.encode('utf-8'))

            self._last_cmd_time = time.time()

    async def status(self):
        """Return the state of the device."""
        return self._state

    async def power_off(self):
        """Power the device off."""
        await self.exec_command(CMD_POWER, '=', False)

    async def power_on(self):
        """Power the device on."""
        await self.exec_command(CMD_POWER, '=', True)

    async def set_volume(self, volume):
        """Set volume level of the device. Accepts integer values -80-0."""
        await self.exec_command(CMD_VOLUME, '=', float(volume))

    async def volume_down(self):
        await self.exec_command(CMD_VOLUME, '-')

    async def volume_up(self):
        await self.exec_command(CMD_VOLUME, '+')

    async def mute(self):
        """Mute the device."""
        await self.exec_command(CMD_MUTE, '=', True)

    async def unmute(self):
        """Unmute the device."""
        await self.exec_command(CMD_MUTE, '=', False)

    async def select_source(self, source):
        """Select a source from the list of sources."""
        await self.exec_command(CMD_SOURCE, '=', source)

    def available_sources(self):
        """Return a list of available sources."""
        return list(C338_CMDS[CMD_SOURCE]['values'])
