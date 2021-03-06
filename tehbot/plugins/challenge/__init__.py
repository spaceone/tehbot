from tehbot.plugins import *
import tehbot.plugins as plugins
import shlex
import importlib
import urllib
import urllib2
import re
import irc.client

__all__ = [ "BaseSite", "NoSuchChallengeError", "NoSuchUserError", "ChallengesNotNumberedError", "plugins" ]

path = __name__

sitemap = {
    "rev" : "revel",
    "revel" : "revel",
    "revolutionelite" : "revel",
    "hs" : "hs",
    "happy-security" : "hs",
    "happysecurity" : "hs",
    "happysec" : "hs",
    "wechall" : "wc",
    "wc" : "wc",
    "nf" : "nf",
    "net-force" : "nf",
    "ht" : "hackthis",
    "hackthis" : "hackthis",
    "wix" : "wix",
    "wixxerd" : "wix"
}

class BaseSite:
    def prefix(self):
        return u"[Challenges]"

    def siteurl(self):
        return "https://www.google.com"

    def userstats(self, user):
        raise NotImplementedError

    def rankstats(self, rank):
        raise NotImplementedError

    def solvers(self, challname, challnr, user):
        raise NotImplementedError

class NoSuchChallengeError(Exception):
    pass

class NoSuchUserError(Exception):
    pass

class ChallengesNotNumberedError(Exception):
    pass


class StatsPlugin(StandardPlugin):
    """Shows current stats for a user on a challenge site."""

    def __init__(self):
        StandardPlugin.__init__(self)
        self.parser.add_argument("user_or_rank", nargs="?")
        self.parser.add_argument("-n", "--numeric", action="store_true")
        group = self.parser.add_mutually_exclusive_group()
        group.add_argument("-s", "--site", choices=sorted(set(sitemap.keys())))
        group.add_argument("-g", "--global", action="store_true")


    def stats(self, site, user, rank):
        try:
            if user:
                res = site.userstats(user)
                if res is None:
                    txt = u"The requested user was not found. You can register at %s." % site.siteurl()
                else:
                    user, solved, solvedmax, rank, usercount, score, scoremax, extra = res
                    ranktext = u" and is on rank %s (of %d)" % (rank, usercount) if rank and usercount is not None else ""
                    if score is not None:
                        ranktext += u" scoring %d (of %d) points" % (score, scoremax) if scoremax is not None else u" scoring %d points" % (score)
                    txt = u"%s solved %d (of %d) challenges%s.%s"% (user, solved, solvedmax, ranktext, extra or "")
            else:
                res = site.rankstats(rank)
                if res is None:
                    txt = u"No user is at rank %d." % rank
                else:
                    score, who = res
                    txt = ", ".join(who) + (" is" if len(who) == 1 else " are") + " at rank %d with %d challenge%s solved." % (rank, score, "s" if score else "")
        except Exception as e:
            return u"%s %s" % (plugins.red(site.prefix()), plugins.exc2str(e))

        return u"%s %s" % (plugins.green(site.prefix()), txt)

    def execute(self, connection, event, extra, dbconn):
        self.parser.set_defaults(user_or_rank=event.source.nick)
        self.parser.set_defaults(site=event.target[1:] if irc.client.is_channel(event.target) else event.target)

        try:
            pargs = self.parser.parse_args(extra["args"])
            if self.parser.help_requested:
                return self.parser.format_help().strip()
            user, rank = None, None
            if pargs.numeric:
                rank = int(pargs.user_or_rank)
            else:
                user = pargs.user_or_rank
            site = pargs.site.lower()
            glob = vars(pargs)["global"]
        except Exception as e:
            return u"Error: %s" % unicode(e)

        if glob:
            wcurl = "https://www.wechall.net/wechall.php?%s"
            username = str(rank) if rank else user
            query = urllib.urlencode({"username" : plugins.to_utf8(username)})
            res = plugins.from_utf8(urllib2.urlopen(wcurl % query).read())
            return "\x0303[WeChall Global]\x03 " + res

        if not sitemap.has_key(site):
            return u"Unknown site: %s" % site

        try:
            module = importlib.import_module("." + sitemap[site], path)
            globals()[module.__name__] = module
            site = module.Site()
            site.settings = self.settings
        except Exception as e:
            print e
            return u"SiteImportError: %s" % site

        return self.stats(site, user, rank)

register_plugin("stats", StatsPlugin())

class SolversPlugin(StandardPlugin):
    """Shows how many solved a challenge."""

    def __init__(self):
        StandardPlugin.__init__(self)
        self.parser.add_argument("challenge_name_or_nr", nargs="+")
        self.parser.add_argument("-n", "--numeric", action="store_true")
        self.parser.add_argument("-s", "--site", choices=sorted(set(sitemap.keys())))
        self.parser.add_argument("-u", "--user")

    def solvers(self, site, challenge_name_or_nr, user=None):
        try:
            if user is not None and not site.userstats(user):
                raise NoSuchUserError

            if isinstance(challenge_name_or_nr, int):
                res = site.solvers(None, int(challenge_name_or_nr), user)
            else:
                res = site.solvers(challenge_name_or_nr, None, user)

            nr, name, cnt, solvers, solved = res
            pre = u"Challenge Nr. %d, %s, " % (nr, name) if nr is not None else u"Challenge '%s' " % name
            if cnt == 0:
                txt = pre + u"hasn't been solved by anyone yet."
            else:
                if user is not None:
                    txt = pre + u"has%s been solved by %s." % ("" if solved else " not", user)
                else:
                    txt = pre + u"has been solved by %d user%s." % (cnt, "" if cnt == 1 else "s")
                    if cnt > 0 and solvers:
                        txt += u" Last by %s." % u", ".join(solvers[:5])
        except Exception as e:
            return u"%s %s" % (plugins.red(site.prefix()), plugins.exc2str(e))

        return u"%s %s" % (plugins.green(site.prefix()), txt)

    def execute(self, connection, event, extra, dbconn):
        self.parser.set_defaults(site=event.target[1:] if irc.client.is_channel(event.target) else event.target)

        try:
            pargs = self.parser.parse_args(extra["args"])
            if self.parser.help_requested:
                return self.parser.format_help().strip()
            challenge_name_or_nr = " ".join(pargs.challenge_name_or_nr)
            if pargs.numeric:
                challenge_name_or_nr = int(challenge_name_or_nr)
            site = pargs.site.lower()
            user = pargs.user
        except Exception as e:
            return u"Error: %s" % unicode(e)

        if not sitemap.has_key(site):
            return u"Unknown site: %s" % site

        try:
            module = importlib.import_module("." + sitemap[site], path)
            globals()[module.__name__] = module
            site = module.Site()
            site.settings = self.settings
        except Exception as e:
            print e
            return u"SiteImportError: %s" % site

        return self.solvers(site, challenge_name_or_nr, user)

register_plugin("solvers", SolversPlugin())
