from tehbot.plugins import *
import tehbot.plugins as plugins
import wolframalpha
import re
import pipes
import random

class AiHandler(ChannelHandler):
    @staticmethod
    def decision_answers():
        return [
                "Yes",
                "No",
                "Sure",
                "Absolutely",
                "For sure",
                "No, you are!",
                "Will you ever get sick of this?",
                "Certainly not",
                "I haven't made up my mind yet."
                ]

    def initialize(self, dbconn):
        ChannelHandler.initialize(self, dbconn)
        try:
            self.client = wolframalpha.Client(self.settings["wolframalpha_app_id"])
            self.ai_enabled = True
        except:
            self.ai_enabled = False

    def execute(self, connection, event, extra, dbconn):
        botname = self.tehbot.settings.value("botname", connection)
        decide_regex = [
                re.compile(r'''^(?:ok(?:ay)?|hey)\s+%s,?\s*(?:is|are|has|was|were)\s+\w[\s\w]*\?''' % botname, re.I),
                ]
        regex = [
                re.compile(r'''^(?:ok(?:ay)?|hey)\s+%s,?\s*(?P<what>.*?)\s*\??$''' % botname, re.I),
                ]
        solved_regex = [
                re.compile(r'''^(?:ok(?:ay)?|hey)\s+%s,?\s*has\s+(?P<who>\w+)\s+solved\s+(?P<chall>\w[\s\w]*?|"[^"]+"|'[^']+')(?:\s+on\s+(?P<site>\w[\s\w]*?|"[^"]+"|'[^']+'))?\s*\??$''' % botname, re.I),
                re.compile(r'''^(?:ok(?:ay)?|hey)\s+%s,?\s*did\s+(?P<who>\w+)\s+solve\s+(?P<chall>\w[\s\w]*?|"[^"]+"|'[^']+')(?:\s+on\s+(?P<site>\w[\s\w]*?|"[^"]+"|'[^']+'))?\s*\??$''' % botname, re.I)
                ]

        for r in solved_regex:
            match = r.search(extra["msg"])
            if match is not None:
                user = match.group(1)
                chall = match.group(2)
                site = match.group(3)

                plugin = self.tehbot.cmd_handlers["solvers"]
                chall = " ".join(plugins.mysplit(chall))
                args = '-u %s %s' % (user, pipes.quote(chall))
                if site is not None:
                    site = " ".join(plugins.mysplit(site))
                    args = args + " -s %s" % pipes.quote(site)
                plugin.handle(connection, event, {"args":args}, dbconn)
                return

        if not self.ai_enabled:
            return

        for r in decide_regex:
            match = r.search(extra["msg"])
            if match is not None:
                return random.choice(AiHandler.decision_answers())

        for r in regex:
            match = r.search(extra["msg"])
            if match is not None:
                what = match.group(1)

                try:
                    for p in self.client.query(what).pods:
                        if p.id == "Result" and p.text:
                            txt = " ".join(p.text.splitlines())
                            return plugins.shorten("%s: %s" % (event.source.nick, txt), 350)

                    for p in self.client.query(what).pods:
                        if p.id == "Misc" and p.text:
                            txt = " ".join(p.text.splitlines())
                            print txt

                    raise Exception("hm")
                except:
                    return [("me", "shrugs")]

register_channel_handler(AiHandler())
