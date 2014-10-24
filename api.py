import collections
import mmap
import os
import struct
import yaml # Requires PyYAML

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

MEMMAPFILE = 'Local\\IRSDKMemMapFileName'
MEMMAPFILESIZE = 798720 # Hopefully this is fairly static...
MEMMAPFILE_START = '\x01' # Used to detect memory mapped file exists

HEADER_LEN = 144

# How far into a header the name sits, and its max length
TELEM_NAME_OFFSET = 16
TELEM_NAME_MAX_LEN = 32

# There appears to be triple-buffering of data
VAL_BUFFERS = 3

# The mapping between the type integer in memory mapped file and Python's struct
TYPEMAP = ['c', '?', 'i', 'I', 'f', 'd']


class API(object):
    """ A basic read-only iRacing Session and Telemetry API client.
    """
    def __init__(self, mmap_object = None):
        """ Sets up a lot of internal variables, they are populated when first
            accessed by their non underscore-prepended versions. This makes the
            first access to a method like telemetry() slower, but massively
            tidies up the codebase.
        """
        self.__var_types = None
        self.__buffer_offsets = None
        self.__sizes = None
        self.__mmp = mmap_object
        self.__var_offsets = None
        self.__telemetry_names = None
        self.__yaml_names = None

        if not self._iracing_alive():
           raise Exception("iRacing memory mapped file could not be found")

    def __getitem__(self, key):
        """ Helper to allow for API()['Speed'] to work.
        """
        if key in self._telemetry_names:
            return self.telemetry(key)
        else:
            return self._yaml_dict[key]

    def _iracing_alive(self):
        """ Returns true if iRacing is running, determined by whether we have a
            memory mapped file or not.
        """
        try:
            self._mmp.seek(0)
            return self._mmp.read(1) == MEMMAPFILE_START
        except:
            return False

    @property
    def _telemetry_header_start(self):
        """ Returns the index of the telemetry header, searching from the end of
            the yaml.
        """
        self._mmp.seek(self._yaml_end)
        dat = '\x00'
        while dat.strip() == '\x00':
            dat = self._mmp.read(1)
        return self._mmp.tell() - 1

    @property
    def _yaml_end(self):
        """ Returns the index of the end of the YAML in memory.
        """
        self._mmp.seek(0)
        offset = 0
        headers = self._mmp.readline()
        while True:
            line = self._mmp.readline()
            if line.strip() == '...':
                break
            else:
                offset += len(line)
        return offset + len(headers) + 4

    @property
    def _mmp(self):
        """ Create the memory map.
        """
        if self.__mmp is None:
            self.__mmp = mmap.mmap(-1, MEMMAPFILESIZE, MEMMAPFILE,
                                  access=mmap.ACCESS_READ)
        return self.__mmp

    @property
    def _sizes(self):
        """ Find the size for each variable, cache the results.
        """
        if self.__sizes is None:
            self.__sizes = {}
            for key, var_type in self._var_types.items():
                self.__sizes[key] = struct.calcsize(var_type)
        return self.__sizes

    @property
    def _buffer_offsets(self):
        """ Find the offsets for the value array(s), cache the result.
        """
        if self.__buffer_offsets is None:
            self.__buffer_offsets = [self._get(52 + (i * 16), 'i')
                                    for i
                                    in range(VAL_BUFFERS)]
        return self.__buffer_offsets

    @property
    def _telemetry_names(self):
        """ The names of the telemetry variables, in order in memory, cached.
            TODO: Make less clunky...
        """
        if self.__telemetry_names is None:
            self.__telemetry_names = []
            self._mmp.seek(self._telemetry_header_start)
            while True:
                pos = self._mmp.tell() + TELEM_NAME_OFFSET
                start = TELEM_NAME_OFFSET
                end = TELEM_NAME_OFFSET + TELEM_NAME_MAX_LEN
                header = self._mmp.read(HEADER_LEN)
                name = header[start:end].replace('\x00','')
                if name == '':
                    break
                self.__telemetry_names.append(name)
        return self.__telemetry_names

    @property
    def _var_types(self):
        """ Set up the type map based on the headers, cache the results.
        """
        if self.__var_types is None:
            self.__var_types = {}
            for i, name in enumerate(self._telemetry_names):
                type_loc = self._telemetry_header_start + (i * HEADER_LEN)
                self.__var_types[name] = TYPEMAP[int(self._get(type_loc, 'i'))]
        return self.__var_types

    @property
    def _var_offsets(self):
        """ Find the offsets between the variables - used to find values in real
            time. Results are cached.
        """
        if self.__var_offsets is None:
            self.__var_offsets = {}
            offsets_seek = self._get(28, 'i')
            for i, name in enumerate(self._telemetry_names):
                offset = self._get(offsets_seek + (i * HEADER_LEN) + 4, 'i')
                self.__var_offsets[name] = offset
        return self.__var_offsets

    @property
    def _yaml_dict(self):
        """ Returns the session yaml as a nested dict.
        """
        ymltxt = ''
        self._mmp.seek(0)
        headers = self._mmp.readline()
        return yaml.load(self._mmp[self._mmp.tell():self._yaml_end],
                         Loader=Loader)

    def _get(self, position, type):
        """ Gets a value from the mmp, based on a position and struct var type.
        """
        size = struct.calcsize(type)
        val = struct.unpack(type, self._mmp[position:position + size])[0]
        if val is None:
            val = 0
        return val

    def keys(self):
        """ Helper to allow this to be semi-dict-like by allowing .keys() calls.
        """
        return sorted(self._yaml_dict.keys() + self._telemetry_names)

    def telemetry(self, key):
        """ Return the data for a telemetry key. There are three buffers and
            this returns the first one with a valid value.

            TODO: Use the "tick" indicator to show which one to use instead of
            this brute-force method.
        """
        val_o = self._var_offsets[key]
        for buf_o in self._buffer_offsets:
            data = self._mmp[val_o + buf_o: val_o + buf_o + self._sizes[key]]
            if len(data.replace('\x00','')) != 0:
                return struct.unpack(self._var_types[key], data)[0]

if __name__ == '__main__':
    """ Simple test usage.
    """
    client = API()
    for key in client.keys():
        print key, client[key]
