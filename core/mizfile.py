import io
import os
import re
import tempfile
import zipfile
from datetime import datetime
from typing import Union


class MizFile:
    re_exp = {
        'start_time': r'^    \["start_time"\] = (?P<start_time>.*),',
        'key_value': r'\["{key}"\] = (?P<value>.*),'
    }

    def __init__(self, filename: str):
        self.filename = filename
        self.mission = []
        self._load()

    def _load(self):
        with zipfile.ZipFile(self.filename, 'r') as miz:
            with miz.open('mission') as mission:
                self.mission = io.TextIOWrapper(mission, encoding='utf-8').readlines()

    def save(self):
        tmpfd, tmpname = tempfile.mkstemp(dir=os.path.dirname(self.filename))
        os.close(tmpfd)
        with zipfile.ZipFile(self.filename, 'r') as zin:
            with zipfile.ZipFile(tmpname, 'w') as zout:
                zout.comment = zin.comment  # preserve the comment
                for item in zin.infolist():
                    if item.filename != 'mission':
                        zout.writestr(item, zin.read(item.filename))
                    else:
                        zout.writestr(item, ''.join(self.mission))
        os.remove(self.filename)
        os.rename(tmpname, self.filename)

    @property
    def start_time(self) -> int:
        exp = re.compile(self.re_exp['start_time'])
        for i in range(len(self.mission), 0):
            match = exp.search(self.mission[i])
            if match:
                return int(match.group('start_time'))

    @start_time.setter
    def start_time(self, value: Union[int, str]) -> None:
        if isinstance(value, int):
            start_time = value
        else:
            start_time = int((datetime.strptime(value, "%H:%M") - datetime(1900, 1, 1)).total_seconds())
        exp = re.compile(self.re_exp['start_time'])
        for i in range(0, len(self.mission)):
            match = exp.search(self.mission[i])
            if match:
                self.mission[i] = re.sub(' = ([^,]*)', ' = {}'.format(start_time), self.mission[i])
                break

    @property
    def date(self) -> datetime:
        exp = {}
        date = {}
        for x in ['Day', 'Month', 'Year']:
            exp[x] = re.compile(self.re_exp['key_value'].format(key=x))
        for i in range(0, len(self.mission)):
            for x in ['Day', 'Month', 'Year']:
                match = exp[x].search(self.mission[i])
                if match:
                    date[x] = int(match.group('value'))
        return datetime(date['Year'], date['Month'], date['Day'])

    @date.setter
    def date(self, value: datetime) -> None:
        exp = {}
        date = {"Year": value.year, "Month": value.month, "Day": value.day}
        for x in ['Day', 'Month', 'Year']:
            exp[x] = re.compile(self.re_exp['key_value'].format(key=x))
        for i in range(0, len(self.mission)):
            for x in ['Day', 'Month', 'Year']:
                match = exp[x].search(self.mission[i])
                if match:
                    self.mission[i] = re.sub(' = ([^,]*)', ' = {}'.format(date[x]), self.mission[i])

    @property
    def temperature(self) -> int:
        exp = re.compile(self.re_exp['key_value'].format(key='temperature'))
        for i in range(len(self.mission), 0):
            match = exp.search(self.mission[i])
            if match:
                return int(match.group('value'))

    @temperature.setter
    def temperature(self, value: int) -> None:
        exp = re.compile(self.re_exp['key_value'].format(key='temperature'))
        for i in range(0, len(self.mission)):
            match = exp.search(self.mission[i])
            if match:
                self.mission[i] = re.sub(' = ([^,]*)', ' = {}'.format(value), self.mission[i])
                break

    @property
    def atmosphere_type(self) -> int:
        exp = re.compile(self.re_exp['key_value'].format(key='atmosphere_type'))
        for i in range(len(self.mission), 0):
            match = exp.search(self.mission[i])
            if match:
                return int(match.group('value'))

    @atmosphere_type.setter
    def atmosphere_type(self, value: int) -> None:
        exp = re.compile(self.re_exp['key_value'].format(key='atmosphere_type'))
        for i in range(0, len(self.mission)):
            match = exp.search(self.mission[i])
            if match:
                self.mission[i] = re.sub(' = ([^,]*)', ' = {}'.format(value), self.mission[i])
                break

    @property
    def preset(self) -> str:
        exp = re.compile(self.re_exp['key_value'].format(key='preset'))
        for i in range(len(self.mission), 0):
            match = exp.search(self.mission[i])
            if match:
                return match.group('value').replace('"', '')

    @preset.setter
    def preset(self, value) -> None:
        # We're using a preset, so disable dynamic weather
        if self.atmosphere_type == 1:
            self.atmosphere_type = 0
        exp = re.compile(self.re_exp['key_value'].format(key='preset'))
        for i in range(0, len(self.mission)):
            match = exp.search(self.mission[i])
            if match:
                self.mission[i] = re.sub(' = ([^,]*)', ' = "{}"'.format(value), self.mission[i])
                return
        # If we are here, no preset was set
        for i in range(0, len(self.mission)):
            if '["clouds"] =' in self.mission[i]:
                self.mission.insert(i + 4, f'            ["preset"] = "{value}",\n')
                break

    @property
    def wind(self) -> dict:
        exp_speed = re.compile(self.re_exp['key_value'].format(key='speed'))
        exp_dir = re.compile(self.re_exp['key_value'].format(key='dir'))
        wind = {}
        for key in ['atGround', 'at2000', 'at8000']:
            exp = re.compile(self.re_exp['key_value'].format(key=key))
            for i in range(0, len(self.mission)):
                match = exp.search(self.mission[i])
                if match:
                    wind['key'] = {
                        "speed": exp_speed.search(self.mission[i + 2]).group('value'),
                        "dir": exp_dir.search(self.mission[i + 3]).group('value')
                    }
        return wind

    @wind.setter
    def wind(self, values: dict) -> None:
        for key, value in values.items():
            for i in range(0, len(self.mission)):
                if f'["{key}"] = ' in self.mission[i]:
                    if 'speed' in value:
                        self.mission[i + 2] = re.sub(' = ([^,]*)', ' = {}'.format(value['speed']), self.mission[i + 2])
                    if 'dir' in value:
                        self.mission[i + 3] = re.sub(' = ([^,]*)', ' = {}'.format(value['dir']), self.mission[i + 3])
                    break