import plugins
import settings
import irc.client
import threading
from Queue import Empty
import traceback
import sqlite3
import time
import re
import datetime
import functools

import os.path
from types import ModuleType

import ctypes

def _terminate_thread(thread):
    """Terminates a python thread from another thread.

    :param thread: a threading.Thread instance
    """
    if not thread.isAlive():
        return

    exc = ctypes.py_object(SystemExit)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread.ident), exc)
    if res == 0:
        raise ValueError("nonexistent thread id")
    elif res > 1:
        # """if it returns a number greater than one, you're in trouble,
        # and you should call it again with exc=NULL to revert the effect"""
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread.ident, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")

def _gather(module, modules):
    if module in modules:
        return

    try:
        path = os.path.dirname(module.__file__)
    except:
        return

    if path.startswith(os.path.dirname(__file__)) and os.path.exists(path):
        modules.add(module)
        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)
            if type(attribute) is ModuleType:
                _gather(attribute, modules)


class TehbotImpl:
    def __init__(self, tehbot):
        self.core = tehbot
        self.dispatcher = Dispatcher(self)
        self.operator_cmd_handlers = {}
        self.pub_cmd_handlers = {}
        self.priv_cmd_handlers = {}
        self.channel_handlers = []
        self.channel_join_handlers = []
        self.pollers = []
        self.announcers = []
        plugins._tehbot = self.core
        self.dbfile = os.path.join(os.path.dirname(__file__), "tehbot.sqlite")
        self._dbconn = sqlite3.connect(self.dbfile)
        #self._kill_workers()
        #self.core.quit_called = False
        self._start_workers()


    def collect_plugins(self):
        plugins.collect()
        print "pub  cmd handlers:", sorted(self.pub_cmd_handlers.keys())
        print "priv cmd handlers:", sorted(self.priv_cmd_handlers.keys())
        print "channel  handlers:", sorted(h.__class__.__name__ for h in self.channel_handlers)
        print "chn join handlers:", sorted(h.__class__.__name__ for h in self.channel_join_handlers)
        print "          pollers:", sorted(h.__class__.__name__ for h in self.pollers)
        print "       announcers:", sorted(h.__class__.__name__ for h in self.announcers)

        with self.core.reactor.mutex:
            self.core.reactor.scheduler.queue = []

        for p in self.pollers:
            p._schedule(20)

        for a in self.announcers:
            today = datetime.date.today()
            at = int(today.strftime("%s")) + a.at()
            if at < time.time():
                at += int(datetime.timedelta(days=1).total_seconds())
            print "Scheduling %s at %d" % (a.__class__.__name__, at)
            a._schedule(at)

    def gather_modules(self):
        modules = set()
        _gather(plugins, modules)
        modules.remove(plugins)
        return modules

    def _process(self):
        dbconn = sqlite3.connect(self.dbfile)

        while True:
            try:
                plugin, args = self.core.queue.get(timeout=1)
                plugin.handle(*args, dbconn=dbconn)
                self.core.queue.task_done()
            except Empty:
                pass
            except:
                traceback.print_exc()

            dbconn.rollback()

            if self.core.quit_called:
                break

        dbconn.close()

    def _kill_workers(self):
        while self.core.workers:
            _terminate_thread(self.core.workers.pop())

    def _start_workers(self):
        while len(self.core.workers) < settings.nr_worker_threads:
            worker = threading.Thread(target=self._process)
            self.core.workers.append(worker)
            worker.start()

    def _get_connection(self, name):
        for c in self.core.reactor.connections:
            if c.name == name:
                return c
        return None

    def connect(self):
        for name in settings.connections:
            print "Connecting to %s" % name
            conn = self.core.reactor.server()
            conn.name = name
            conn.locks = dict()
            self.reconnect(conn)

    def reconnect(self, connection):
        params = settings.connections[connection.name]

        if params.use_ssl:
            import ssl
            factory = irc.client.connection.Factory(wrapper=ssl.wrap_socket)
        else:
            factory = irc.client.connection.Factory()
        connection.connect(params.host, params.port, settings.bot_name, params.bot_password, settings.bot_name, settings.bot_name, factory)
        connection.set_rate_limit(4)
        connection.set_keepalive(60)

    def process_once(self, timeout):
        self.core.reactor.process_once(timeout)

    def quit(self, msg=None):
        print "quit called"
        self.core.quit_called = True
        self.core.reactor.disconnect_all(msg or "bye-bye")
        raise SystemExit

    def kbd_reload(self, args):
        self.core.reload()

    def kbd_quit(self, args):
        self.quit(args)

    def kbd_stats(self, args):
        print "Connections"
        for c in self.core.reactor.connections:
            print " * %s: %s" % (c.name, "connected" if c.is_connected() else "not connected")

        print "Delayed Commands"
        for c in self.core.reactor.scheduler.queue:
            print " * %s at %s" % (c.target.func if isinstance(c.target, functools.partial) else c.target, c)

        print "Authenticated nicks"
        for c, nicks in self.dispatcher.authnicks._nicks.items():
            print " * %s" % (c.name)
            for n, vals in nicks.items():
                print "  * %s: %s" % (n, vals)


class AuthNicks:
    _nicks = dict()

    def put(self, connection, nick, account):
        self._init(connection, nick)
        self._nicks[connection][nick]["accounts"].add(account)

    def _init(self, connection, nick):
        if not self._nicks.has_key(connection):
            self._nicks[connection] = dict()
        if not self._nicks[connection].has_key(nick):
            self._nicks[connection][nick] = { "cmds" : [], "accounts" : set() }

    def contains(self, connection, nick, account):
        try:
            return account in self._nicks[connection][nick]["accounts"]
        except KeyError:
            return False

    def remove(self, connection, nick):
        try:
            del self._nicks[connection][nick]
        except KeyError:
            pass

    def commands(self, connection, nick):
        try:
            return self._nicks[connection][nick]["cmds"]
        except KeyError:
            return []

    def put_command(self, connection, nick, cmd):
        self._init(connection, nick)
        try:
            self._nicks[connection][nick]["cmds"].append(cmd)
        except KeyError:
            pass

    def clear_commands(self, connection, nick):
        try:
            self._nicks[connection][nick]["cmds"] = []
        except KeyError:
            pass


class Dispatcher:
    def __init__(self, tehbot):
        self.tehbot = tehbot
        self.authnicks = AuthNicks()

    def _execute_op_cmd(self, connection, source, target, nick, cmd, args):
        self.authnicks.put_command(connection, nick, (cmd, (connection, target, nick, cmd, args, self.tehbot._dbconn)))
        params = settings.connections[connection.name]
        ops = params.ops

        if self._is_op_host(ops, source.host) or self._is_op_nickserv(ops, connection, source.nick):
            for cmd, args in self.authnicks.commands(connection, nick):
                # operator commands are handled in main thread
                self.tehbot.operator_cmd_handlers[cmd].handle(*args)
            self.authnicks.clear_commands(connection, nick)
        else:
            for t, s in ops:
                if t == "nickserv":
                    connection.whois(nick)
                    return

    def _is_op_host(self, ops, host):
        for t, s in ops:
            if t == "host" and s == host:
                return True
        return False

    def _is_op_nickserv(self, ops, connection, nick):
        for t, s in ops:
            if t == "nickserv": 
                if self.authnicks.contains(connection, nick, s):
                    return True
        return False

    def dispatch(self, connection, event):
        method = getattr(self, "on_" + event.type, None)
        types = [ "all_raw_messages", "ping", "pong", "ctcp", "motd", "motdstart", "endofmotd" ]
        if method:
            method(connection, event)
        elif event.type not in types:
            print event.type, event.source, event.target, event.arguments

    def on_whoisaccount(self, connection, event):
        nick = event.arguments[0]
        account = event.arguments[1]
        self.authnicks.put(connection, nick, account)
        params = settings.connections[connection.name]

        for t, s in params.ops:
            if t == "nickserv" and s == account:
                for cmd, args in self.authnicks.commands(connection, nick):
                    # operator commands are handled in main thread
                    self.tehbot.operator_cmd_handlers[cmd].handle(*args)
                self.authnicks.clear_commands(connection, nick)
                break

    def on_nicknameinuse(self, connection, event):
        print "%s: Nick name in use" % connection.name
        print event.type, event.source, event.target, event.arguments
        try:
            newnick = event.arguments[0] + "_"
        except:
            newnick = connection.get_nickname() + "_"
        print "trying new nick: %s" % newnick
        connection.nick(newnick)

    def on_welcome(self, connection, event):
        plugins.myprint("%s: connected to %s" % (connection.name, connection.server))
        self.tehbot.core.reactor.scheduler.execute_after(2, functools.partial(self.join_channels, connection))

    def join_channels(self, connection):
        params = settings.connections[connection.name]
        for ch in params.channels:
            connection.locks[ch] = threading.Lock()

        mchans = ",".join(params.channels)
        plugins.myprint("%s: joining %s" % (connection.name, mchans))
        connection.send_raw("JOIN %s" % mchans)

    def on_disconnect(self, connection, event):
        if self.tehbot.core.quit_called:
            return

        delay = 120
        plugins.myprint("%s: lost connection" % (connection.name))
        plugins.myprint("%s: reconnecting in %d seconds" % (connection.name, delay))

        with self.tehbot.core.reactor.mutex:
            for cmd in self.tehbot.core.reactor.scheduler.queue[:]:
                if isinstance(cmd.target, functools.partial) and cmd.target.args == ('keep-alive',) and cmd.target.func.__self__ == connection:
                    print "removing cmd", cmd
                    self.tehbot.core.reactor.scheduler.queue.remove(cmd)

        self.tehbot.core.reactor.scheduler.execute_after(delay, functools.partial(self.tehbot.reconnect, connection))

    def on_join(self, connection, event):
        plugins.myprint("%s: %s joined" % (event.target, event.source.nick))
        nick = event.source.nick
        channel = event.target

        if nick == settings.bot_name:
            return

        if nick == "wence":
            return

        for h in self.tehbot.channel_join_handlers:
            self.tehbot.core.queue.put((h, (connection, channel, nick)))

    def on_part(self, connection, event):
        plugins.myprint("%s: %s left" % (event.target, event.source.nick))
        self.authnicks.remove(connection, event.source.nick)

    def on_quit(self, connection, event):
        plugins.myprint("%s: %s has quit (%s)" % (connection.name, event.source.nick, event.arguments[0]))
        self.authnicks.remove(connection, event.source.nick)

        # reconquer our nick!
        if event.source.nick == settings.bot_name:
            connection.nick(settings.bot_name)

    def on_action(self, connection, event):
        msg = event.arguments[0]
        nick = event.source.nick

        if irc.client.is_channel(event.target):
            target = event.target
        else:
            target = nick

        plugins.myprint("%s: *%s %s" % (target, nick, msg))

    def react_to_command(self, connection, event, msg):
        tmp = msg.split(" ", 1)
        cmd = tmp[0]
        args = tmp[1] if len(tmp) == 2 else None
        nick = event.source.nick

        if nick == "jayssj11":
            return

        if irc.client.is_channel(event.target):
            target = event.target
        else:
            target = nick

        if cmd in self.tehbot.operator_cmd_handlers:
            self._execute_op_cmd(connection, event.source, target, nick, cmd, args)
        elif irc.client.is_channel(event.target):
            if cmd in self.tehbot.pub_cmd_handlers:
                self.tehbot.core.queue.put((self.tehbot.pub_cmd_handlers[cmd], (connection, target, nick, cmd, args)))
        else:
            if cmd in self.tehbot.priv_cmd_handlers:
                self.tehbot.core.queue.put((self.tehbot.priv_cmd_handlers[cmd], (connection, target, nick, cmd, args)))

    def on_pubmsg(self, connection, event):
        nick = event.source.nick
        channel = event.target
        msg = event.arguments[0]
        plugins.myprint("%s: %s: %s" % (channel, nick, msg))
        # create table Messages(id integer primary key, ts datetime, server varchar, channel varchar, nick varchar, message varchar)
        pattern = r'[\x02\x0F\x16\x1D\x1F]|\x03(?:\d{1,2}(?:,\d{1,2})?)?'
        regex = re.compile(pattern, re.UNICODE)
        msg2 = regex.sub("", msg)

        with self.tehbot._dbconn:
            self.tehbot._dbconn.execute("insert into Messages values(null, ?, ?, ?, ?, ?)", (time.time(), connection.name, channel, nick, msg2))

        # possible command
        if msg and msg[0] == settings.cmd_prefix:
            self.react_to_command(connection, event, msg[1:])
        elif msg:
            tmp = msg.split(" ", 1)
            tonick = tmp[0]
            args = tmp[1] if len(tmp) == 2 else None
            if (tonick == settings.bot_name or tonick[:-1] == settings.bot_name) and args:
                self.react_to_command(connection, event, args)
            for h in self.tehbot.channel_handlers:
                self.tehbot.core.queue.put((h, (connection, channel, nick, msg)))

    def on_privmsg(self, connection, event):
        nick = event.source.nick
        chat = nick
        msg = event.arguments[0]
        plugins.myprint("%s: %s: %s" % (chat, nick, msg))

        # possible command
        if msg and msg[0] == settings.cmd_prefix:
            self.react_to_command(connection, event, msg[1:])
        elif msg:
            tmp = msg.split(" ", 1)
            tonick = tmp[0]
            args = tmp[1] if len(tmp) == 2 else None
            if (tonick == settings.bot_name or tonick[:-1] == settings.bot_name) and args:
                self.react_to_command(connection, event, args)

    def on_nick(self, connection, event):
        oldnick = event.source.nick
        newnick = event.target
        plugins.myprint("%s: %s is now known as %s" % (connection.name, oldnick, newnick))
        self.authnicks.remove(connection, oldnick)

        # reconquer our nick!
        if oldnick == settings.bot_name:
            connection.nick(settings.bot_name)

    def on_396(self, connection, event):
        # TODO join channel before 5s wait time is over
        pass