import os

import psycopg2
import psycopg2.extras
import string
from core import utils
from contextlib import closing
from discord.ext import commands
from os import path
from shutil import copytree, copy2
from .bot import DCSServerBot
from .listener import EventListener


class Plugin(commands.Cog):

    def __init__(self, plugin: str, bot: DCSServerBot, eventlistener: EventListener = None):
        self.plugin = plugin
        self.plugin_version = None
        self.bot = bot
        self.log = bot.log
        self.config = bot.config
        self.pool = bot.pool
        self.install()
        self.eventlistener = eventlistener
        if self.eventlistener:
            self.bot.register_eventListener(self.eventlistener)
        self.log.debug(f'- Plugin {type(self).__name__} initialized.')

    def cog_unload(self):
        if self.eventlistener:
            self.bot.unregister_eventListener(self.eventlistener)
        self.log.debug(f'- Plugin {type(self).__name__} unloaded.')

    def install(self):
        self.init_db()
        for server_name in self.bot.DCSServers.keys():
            installation = utils.findDCSInstallations(server_name)[0]
            source_path = f'./plugins/{self.plugin}/lua'
            if path.exists(source_path):
                target_path = path.expandvars(self.config[installation]['DCS_HOME'] + f'\\Scripts\\net\\DCSServerBot\\{self.plugin}\\')
                copytree(source_path, target_path, dirs_exist_ok=True)
                self.log.debug(f'  => Luas installed into server {server_name}')
        # install reports
        source_path = f'./plugins/{self.plugin}/reports'
        if path.exists(source_path):
            target_path = f'./reports/{self.plugin}'
            if not path.exists(target_path):
                os.makedirs(target_path)
            for file in os.listdir(source_path):
                if not path.exists(os.path.join(target_path, file)):
                    copy2(os.path.join(source_path, file), target_path)
                else:
                    self.log.debug(f'  - skipping already existing report {file}')
            self.log.debug(f'  => Reports installed.')

    def init_db(self):
        tables_file = f'./plugins/{self.plugin}/db/tables.sql'
        if path.exists(tables_file):
            conn = self.pool.getconn()
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute('SELECT version FROM plugins WHERE plugin = %s', (self.plugin, ))
                    row = cursor.fetchone()
                    if row:
                        self.plugin_version = row[0]
                        updates_file = f'./plugins/{self.plugin}/db/update_{self.plugin_version}.sql'
                        while path.exists(updates_file):
                            with open(updates_file) as updates_sql:
                                for query in updates_sql.readlines():
                                    self.log.debug(query.rstrip())
                                    cursor.execute(query.rstrip())
                            cursor.execute('SELECT version FROM plugins WHERE plugin = %s', (self.plugin,))
                            self.plugin_version = cursor.fetchone()[0]
                            self.log.info(f'  => {string.capwords(self.plugin)} updated to version {self.plugin_version}.')
                            updates_file = f'./plugins/{self.plugin}/db/update_{self.plugin_version}.sql'
                    else:
                        with open(tables_file) as tables_sql:
                            for query in tables_sql.readlines():
                                self.log.debug(query.rstrip())
                                cursor.execute(query.rstrip())
                        self.log.info(f'  => {string.capwords(self.plugin)} installed.')
                conn.commit()
            except (Exception, psycopg2.DatabaseError) as error:
                self.log.exception(error)
            finally:
                self.pool.putconn(conn)


class PluginRequiredError(Exception):

    def __init__(self, plugin):
        super().__init__(f'Required plugin "{string.capwords(plugin)}" is missing!')
