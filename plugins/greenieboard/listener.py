import asyncio
import os
import psycopg2
import re
import string
import sys
import uuid
from contextlib import closing
from core import EventListener, Server, Player, Channel, Side, Plugin, PersistentReport
from matplotlib import pyplot as plt
from pathlib import Path
from plugins.creditsystem.player import CreditPlayer
from plugins.greenieboard import get_element
from typing import Optional, cast


class GreenieBoardEventListener(EventListener):

    EVENT_TEXTS = {
        Side.BLUE: {
            'waveoff': '```ansi\n\u001b[0;34mBLUE player {} waved off from carrier {}.```',
            'bolter': '```ansi\n\u001b[0;34mBLUE player {} boltered from carrier {}.```',
            'landing': '```ansi\n\u001b[0;34mBLUE player {} landed on carrier {} with grade {} / {}.```'
        },
        Side.RED: {
            'waveoff': '```ansi\n\u001b[0;31mRED player {} waved off from carrier {}.```',
            'bolter': '```ansi\n\u001b[0;31mRED player {} boltered from carrier {}.```',
            'landing': '```ansi\n\u001b[0;31mRED player {} landed on carrier {} with grade {} / {}.```'
        }
    }

    def __init__(self, plugin: Plugin):
        super().__init__(plugin)
        config = self.locals['configs'][0]
        if 'FunkMan' in config:
            sys.path.append(config['FunkMan']['install'])
            from funkman.funkplot.funkplot import FunkPlot
            self.funkplot = FunkPlot(ImagePath=config['FunkMan']['IMAGEPATH'])

    def _update_greenieboard(self, server: Server):
        # shall we render the server specific board?
        config = self.plugin.get_config(server)
        if 'persistent_channel' in config:
            if 'persistent_board' in config and not config['persistent_board']:
                return
            channel_id = int(config['persistent_channel'])
            num_rows = config['num_rows'] if 'num_rows' in config else 10
            report = PersistentReport(self.bot, self.plugin_name, 'greenieboard.json',
                                      server, f'greenieboard-{server.name}', channel_id=channel_id)
            self.bot.loop.call_soon(asyncio.create_task, report.render(server_name=server.name,
                                                                       num_rows=num_rows))
        # shall we render the global board?
        config = self.locals['configs'][0]
        if 'persistent_channel' in config and server == list(self.bot.servers.values())[0]:
            if 'persistent_board' in config and not config['persistent_board']:
                return
            channel_id = int(config['persistent_channel'])
            num_rows = config['num_rows'] if 'num_rows' in config else 10
            report = PersistentReport(self.bot, self.plugin_name, 'greenieboard.json',
                                      server, f'greenieboard', channel_id=channel_id)
            self.bot.loop.call_soon(asyncio.create_task, report.render(server_name=None, num_rows=num_rows))

    async def _send_chat_message(self, player: Player, data: dict):
        server: Server = self.bot.servers[data['server_name']]
        chat_channel = server.get_channel(Channel.CHAT)
        if chat_channel is not None:
            carrier = data['place']['name']
            if 'WO' in data['grade']:
                await chat_channel.send(self.EVENT_TEXTS[player.side]['waveoff'].format(player.name, carrier))
            elif data['grade'] == 'B':
                await chat_channel.send(self.EVENT_TEXTS[player.side]['bolter'].format(player.name, carrier))
            else:
                details = data['details']
                if 'wire' in data and data['wire']:
                    details += f" WIRE# {data['wire']}"
                await chat_channel.send(self.EVENT_TEXTS[player.side]['landing'].format(
                    player.name, carrier, data['grade'].replace('_', '\\_'), details))

    async def registerDCSServer(self, data: dict):
        server: Server = self.bot.servers[data['server_name']]
        try:
            self._update_greenieboard(server)
        except FileNotFoundError as ex:
            self.log.error(f'  => File not found: {ex}')

    def _process_lso_event(self, config: dict, server: Server, player: Player, data: dict):
        time = (int(server.current_mission.start_time) + int(data['time'])) % 86400
        night = time > 20 * 3600 or time < 6 * 3600
        points = data['points'] if 'points' in data else config['ratings'][data['grade']]
        if 'credits' in config and config['credits']:
            cp: CreditPlayer = cast(CreditPlayer, player)
            cp.audit('Landing', cp.points, f"Landing on {data['place']} with grade {data['grade']}.")
            cp.points += points
        case = data['case'] if 'case' in data else 1 if not night else 3
        wire = data['wire'] if 'wire' in data else None
        conn = self.pool.getconn()
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute("INSERT INTO greenieboard (mission_id, player_ucid, unit_type, grade, comment, place, "
                               "trapcase, wire, night, points, trapsheet) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                               (server.mission_id, player.ucid, player.unit_type, data['grade'].strip(),
                                data['details'], data['place']['name'], case, wire, night, points,
                                data['trapsheet'] if 'trapsheet' in data else None))
            conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            conn.rollback()
            self.log.exception(error)
        finally:
            self.pool.putconn(conn)

    @staticmethod
    def _normalize_airboss_lso_rating(grade: str) -> Optional[str]:
        if '<SH>' in grade:
            grade = grade[:-4]
        if grade == 'CUT':
            grade = 'C'
        if 'BOLTER' in grade:
            grade = 'B'
        return grade

    def get_trapsheet(self, config: dict, server: Server, player: Player, data: dict) -> Optional[str]:
        dirname = os.path.expandvars(self.bot.config[server.installation]['DCS_HOME'] + os.path.sep +
                                     config['Moose.AIRBOSS']['basedir'])
        carrier = data['place']['name'].split()[0]
        if 'trapsheet' not in data:
            name = re.sub(f"[{string.punctuation}]", "", player.name).strip()
            filename = config['Moose.AIRBOSS']['trapsheets'].format(
                carrier=carrier, name=name, unit_type=player.unit_type, number='*')
        else:
            filename = data['trapsheet'] + "_{unit_type}*.csv".format(unit_type=player.unit_type)
        p = Path(dirname)
        try:
            return max(p.glob(filename), key=lambda x: x.stat().st_mtime).__str__()
        except Exception as ex:
            self.log.exception(ex)
            self.log.error(f'GreenieBoard: No trapsheet with pattern ({filename}) could be found!')
            return None

    def _process_airboss_event(self, config: dict, server: Server, player: Player, data: dict):
        data['grade'] = self._normalize_airboss_lso_rating(data['grade'])
        data['trapsheet'] = self.get_trapsheet(config, server, player, data)
        self._process_lso_event(config, server, player, data)

    def _process_sc_event(self, config: dict, server: Server, player: Player, data: dict):
        data['details'] = get_element(data['comment'], 'details')
        data['grade'] = get_element(data['comment'], 'grade').replace('---', '--')
        data['wire'] = get_element(data['comment'], 'wire')
        self._process_lso_event(config, server, player, data)

    def _process_funkman_event(self, config: dict, server: Server, player: Player, data: dict):
        if data['grade'] != 'WO':
            filepath = os.path.expandvars(self.bot.config[server.installation]['DCS_HOME']) + \
                       os.path.sep + (config['FunkMan']['basedir'] if 'basedir' in config['FunkMan'] else 'trapsheets')
            if not os.path.exists(filepath):
                os.mkdir(filepath)
            filename = filepath + os.path.sep + f'{uuid.uuid4()}.png'
            fig, _ = self.funkplot.PlotTrapSheet(data)
            fig.savefig(filename, bbox_inches='tight', facecolor='#2C2F33')
            plt.close(fig)
            data['trapsheet'] = filename
        else:
            del data['trapsheet']
        data['grade'] = self._normalize_airboss_lso_rating(data['grade'])
        data['place'] = {
            'name': data['carriername']
        }
        data['time'] = sum(x * int(t) for x, t in zip([3600, 60, 1], data['mitime'].split(":"))) - int(server.current_mission.start_time)
        self._process_lso_event(config, server, player, data)

    async def onMissionEvent(self, data: dict):
        if 'initiator' not in data:
            return
        server: Server = self.bot.servers[data['server_name']]
        config = self.plugin.get_config(server)
        # ignore SC / Moose.AIRBOSS events, if FunkMan is enabled
        if 'FunkMan' in config:
            return
        player: Player = server.get_player(name=data['initiator']['name']) if 'name' in data['initiator'] else None
        if player:
            update = False
            if 'Moose.AIRBOSS' in config:
                if data['eventName'] == 'S_EVENT_AIRBOSS':
                    self._process_airboss_event(config, server, player, data)
                    update = True
            elif data['eventName'] == 'S_EVENT_LANDING_QUALITY_MARK':
                self._process_sc_event(config, server, player, data)
                update = True
            if update:
                await self._send_chat_message(player, data)
                self._update_greenieboard(server)

    async def moose_lso_grade(self, data: dict):
        server: Server = self.bot.servers[data['server_name']]
        config = self.plugin.get_config(server)
        player: Player = server.get_player(name=data['name']) if 'name' in data else None
        if player:
            self._process_funkman_event(config, server, player, data)
            await self._send_chat_message(player, data)
            self._update_greenieboard(server)
