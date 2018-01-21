from tehbot.plugins import *
import tehbot.plugins as plugins
import urllib
import urllib2
import lxml.html
import shlex

class TranslatePlugin(Plugin):
    def __init__(self):
        Plugin.__init__(self)
        self.parser = plugins.ThrowingArgumentParser(
                prog="translate",
                description=TranslatePlugin.__doc__
        )
        self.parser.add_argument("words", metavar='W', nargs="+")
        self.parser.add_argument("-f", "--from-lang", default="auto")
        self.parser.add_argument("-t", "--to-lang", default="en")

    def execute(self):
        try:
            pargs = self.parser.parse_args(self.args, decode=False)
            if self.parser.help_requested:
                return self.parser.format_help().strip()
        except Exception as e:
            return "Error: %s" % str(e)

        if not pargs.words:
            return

        headers = { 'User-Agent' : 'Mozilla/5.0 (X11; Linux x86_64; rv:14.0) Gecko/20100101 Firefox/14.0.1' }
        data = {
                'sl' : pargs.from_lang,
                'tl' : pargs.to_lang,
                'hl' : 'en',
                'ie' : 'UTF-8',
                'q' : ' '.join(pargs.words)
        }

        try:
            req = urllib2.Request("https://translate.google.com/?%s" % urllib.urlencode(data), headers=headers)
            tree = lxml.html.parse(urllib2.urlopen(req))

            trans = tree.xpath("//span[@id='result_box']")
            if len(trans) > 0:
                txt = trans[0].text_content().strip()
                return "\x0303[Translation]\x03 %s" % txt
        except urllib2.HTTPError as h:
            return "\x0304[HTTP Error]\x03 %s" % str(h)
        except Exception as e:
            return "\x0304[Error]\x03 %s" % str(e)

p = TranslatePlugin()
register_cmd("translate", p)
register_cmd("tr", p)