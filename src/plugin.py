# Copyright (C) 2026 by xcentaurix

import os
import re
from time import strftime, localtime
from urllib.parse import quote

from Components.ActionMap import ActionMap, HelpableActionMap
from Components.config import config
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.HelpMenu import HelpableScreen
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Directories import fileExists
from twisted.internet import threads

from enigma import eServiceReference
from skin import parameters

from . import _
from .SamsungTVConfig import getselectedregions, NUMBER_OF_LIVETV_BOUQUETS
from .SamsungTVRequest import samsungRequest
from .SamsungTVDownload import SamsungTVDownload, Silent
from .PiconFetcher import PiconFetcher
from .Variables import TIMER_FILE, PLUGIN_FOLDER, BOUQUET_FILE, PLUGIN_ICON


class SamsungTV(Screen, HelpableScreen):
    skin = f"""
        <screen name="SamsungTV" zPosition="2" position="0,0" resolution="1920,1080" size="1920,1080" flags="wfNoBorder" title="Samsung TV Plus" transparent="0">
            <ePixmap pixmap="{PLUGIN_FOLDER}/images/samsungtv-backdrop.jpg" position="0,0" size="1920,1080" zPosition="-2" alphatest="off" />
            <eLabel position="70,30" size="1780,90" zPosition="1" backgroundColor="#16101113" cornerRadius="12"/><!-- header background -->
            <ePixmap pixmap="{PLUGIN_FOLDER}/images/logo.png" position="70,30" size="486,90" zPosition="5" alphatest="blend" transparent="1" scale="1"/>
            <widget source="global.CurrentTime" render="Label" position="e-400,48" size="300,55" font="Regular; 43" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
                <convert type="ClockToText">Format:%H:%M</convert>
            </widget>
            
            <widget name="loading" position="center,center" size="800,60" font="Regular;50" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
            <widget source="playlist" render="Label" position="400,48" size="1150,55" font="Regular;40" backgroundColor="#00000000" transparent="5" foregroundColor="#00ffff00" zPosition="2" halign="center" />

            <widget source="updated" render="Label" position="70,950" size="615,50" zPosition="1" backgroundColor="#16101113" foregroundColor="#16101113" font="Regular;1"><!-- updated background -->
                <convert type="ConditionalShowHide"/>
            </widget>
            <widget source="updated" render="Label" position="70,950" size="615,50" font="Regular;25" zPosition="5" transparent="1" valign="center" halign="center"/>

            <eLabel position="0,e-60" size="1920,60" zPosition="1" backgroundColor="#16101113" cornerRadius="12"/><!-- key background -->
            <widget addon="ColorButtonsSequence" connection="key_red,key_green"
                textColors="key_red:#00ff0808,key_green:#0004c81b"
                position="224,1030" size="1694,42" font="Regular;33" backgroundColor="#00000000" transparent="1" alignment="left" zPosition="10" spacing="10" />
            <ePixmap pixmap="buttons/key_menu.png" alphatest="blend" position="30,1031" size="52,38" backgroundColor="#00000000" transparent="1" zPosition="2"/>
            <ePixmap pixmap="buttons/key_help.png" alphatest="blend" position="82,1031" size="52,38" backgroundColor="#00000000" transparent="1" zPosition="2"/>
        </screen>"""

    def __init__(self, session):
        self.session = session
        self.skinName = "PlutoTV"
        Screen.__init__(self, session)
        HelpableScreen.__init__(self)

        self.colors = parameters.get("SamsungTvColors", [])

        self.titlemenu = _("Channel Categories")
        self["playlist"] = StaticText(self.titlemenu)
        self["loading"] = Label(_("Loading data... Please wait"))
        self["key_red"] = StaticText(_("Exit"))
        self["key_green"] = StaticText()
        self["updated"] = StaticText()
        self["key_menu"] = StaticText(_("MENU"))

        self["actions"] = HelpableActionMap(
            self, ["SetupActions", "InfobarChannelSelection", "MenuActions"],
            {
                "ok": (self.action, _("Go forward one level including starting playback")),
                "cancel": (self.exit, _("Go back one level including exiting")),
                "save": (self.green, _("Create or update Samsung TV Plus live bouquets")),
                "historyBack": (self.back, _("Go back one level")),
                "menu": (self.loadSetup, _("Open the plugin configuration screen")),
            }, -1
        )

        self.updatebutton()

        if self.updatebutton not in Silent.afterUpdate:
            Silent.afterUpdate.append(self.updatebutton)

        self.initialise()
        self.onLayoutFinish.append(self.getCategories)

    def initialise(self):
        self.region = config.plugins.samsungtv.region.value
        self.channels = []
        self.menu = []
        self.history = []
        self["loading"].show()
        self.title = _("Samsung TV Plus") + " - " + self.titlemenu

    def getCategories(self):
        self.categoryItems = {}
        threads.deferToThread(samsungRequest.getCategories, self.region).addCallback(self.getCategoriesCallback)

    def getCategoriesCallback(self, categories):
        if not categories:
            self.session.open(MessageBox, _("There is no data, it is possible that Samsung TV Plus is not available in your region"), type=MessageBox.TYPE_ERROR, timeout=10)
        else:
            for category in categories:
                self.buildlist(category)
            self.menu.sort(key=lambda x: x.casefold())
            for _key, items in self.categoryItems.items():
                items.sort(key=lambda x: x[1].casefold())
        self["loading"].hide()

    def buildlist(self, category):
        name = category["name"]
        self.categoryItems[name] = []
        self.menu.append(name)
        items = category.get("items", [])
        for item in items:
            itemid = item.get("_id", "")
            if not itemid:
                continue
            itemname = item.get("name", "")
            itemsummary = item.get("summary", "")
            itemgenre = item.get("genre", "")
            itemtype = item.get("type", "channel")
            stream_url = item.get("stream_url", "")
            self.categoryItems[name].append((itemid, itemname, itemsummary, itemgenre, itemtype, stream_url))

    def action(self):
        pass

    def back(self):
        pass

    def playStream(self, name, sid, url=None):
        if url and name:
            string = f"4097:0:0:0:0:0:0:0:0:0:{quote(url)}:{quote(name)}"
            reference = eServiceReference(string)
            if "m3u8" in url.lower() or "jmp2" in url.lower() or "127.0.0.1" in url:
                self.session.open(Samsung_Player, service=reference, sid=sid)

    def green(self):
        self.session.openWithCallback(self.endupdateLive, SamsungTVDownload)

    def endupdateLive(self, _ret=None):
        self.session.openWithCallback(self.updatebutton, MessageBox, _("The Samsung TV Plus bouquets in your channel list have been updated.\n\nThey will now be rebuilt automatically every 5 hours."), type=MessageBox.TYPE_INFO, timeout=10)

    def updatebutton(self, _ret=None):
        with open("/etc/enigma2/bouquets.tv", "r", encoding="utf-8") as f:
            bouquets = f.read()
        if fileExists(TIMER_FILE) and all(((BOUQUET_FILE % cc) in bouquets) for cc in [x for x in getselectedregions() if x]):
            with open(TIMER_FILE, "r", encoding="utf-8") as f:
                last = float(f.read().replace("\n", "").replace("\r", ""))
            updated = strftime(" %x %H:%M", localtime(int(last)))
            self["key_green"].text = _("Update LiveTV Bouquet")
            self["updated"].text = _("LiveTV Bouquet last updated:") + updated
        elif "samsungtv" in bouquets:
            self["key_green"].text = _("Update LiveTV Bouquet")
            self["updated"].text = _("LiveTV Bouquet needs updating. Press GREEN.")
        else:
            self["key_green"].text = _("Create LiveTV Bouquet")
            self["updated"].text = ""

    def exit(self, *_args, **_kwargs):
        if self.history:
            self.back()
        else:
            self.close()

    def loadSetup(self):
        def loadSetupCallback(_result=None):
            if config.plugins.samsungtv.region.value != self.region:
                self.initialise()
                self.getCategories()
        self.session.openWithCallback(loadSetupCallback, SamsungSetup)

    def close(self, *_args, **_kwargs):
        if self.updatebutton in Silent.afterUpdate:
            Silent.afterUpdate.remove(self.updatebutton)
        Screen.close(self)


class SamsungSetup(Setup):
    def __init__(self, session):
        Setup.__init__(self, session, yellow_button={"function": self.yellow}, blue_button={"function": self.blue})
        self.updateYellowButton()
        self.updateBlueButton()
        self.setTitle(_("Samsung TV Plus Setup"))

    def createSetup(self):
        configList = []
        configList.append((_("Region"), config.plugins.samsungtv.region, _("Select the region for the channel list.")))
        configList.append(("---",))
        for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
            if n == 1 or getattr(config.plugins.samsungtv, "live_tv_region" + str(n - 1)).value:
                configList.append((_("LiveTV bouquet %s") % n, getattr(config.plugins.samsungtv, "live_tv_region" + str(n)), _("Region for which LiveTV bouquet %s will be created.") % n))
        configList.append(("---",))
        configList.append((_("Picon type"), config.plugins.samsungtv.picons, _("Using service name picons means they will continue to work even if the service reference changes.")))
        configList.append((_("Data location"), config.plugins.samsungtv.datalocation, _("Used for storing video cover graphics, etc.")))
        self["config"].list = configList

    def updateYellowButton(self):
        if os.path.isdir(PiconFetcher().pluginPiconDir):
            self["key_yellow"].text = _("Remove picons")
        else:
            self["key_yellow"].text = ""

    def updateBlueButton(self):
        with open("/etc/enigma2/bouquets.tv", "r", encoding="utf-8") as f:
            bouquets = f.read()
        if "samsungtv" in bouquets:
            self["key_blue"].text = _("Remove LiveTV Bouquet")
        else:
            self["key_blue"].text = ""

    def yellow(self):
        if self["key_yellow"].text:
            PiconFetcher().removeall()
            self.updateYellowButton()

    def blue(self):
        if self["key_blue"].text:
            Silent.stop()
            from enigma import eDVBDB
            eDVBDB.getInstance().removeBouquet(re.escape(BOUQUET_FILE) % ".*")
            self.updateBlueButton()


class Samsung_Player(MoviePlayer):

    ENABLE_RESUME_SUPPORT = False

    def __init__(self, session, service, sid):
        self.session = session
        self.mpservice = service
        MoviePlayer.__init__(self, self.session, service, sid)
        self.skinName = ["MoviePlayer"]

        self["actions"] = ActionMap(
            ["MoviePlayerActions", "OkActions"],
            {
                "leavePlayerOnExit": self.leavePlayer,
                "leavePlayer": self.leavePlayer,
                "ok": self.toggleShow,
            }, -3
        )
        self.session.nav.playService(self.mpservice)

    def up(self):
        pass

    def down(self):
        pass

    def doEofInternal(self, _playing):
        self.close()

    def leavePlayer(self):
        self.is_closing = True
        self.close()

    def leavePlayerConfirmed(self, answer):
        pass


def sessionstart(reason, session, **_kwargs):  # pylint: disable=unused-argument
    Silent.init(session)
    threads.deferToThread(samsungRequest._getChannelsJson)


def Download_SamsungTV(session, **_kwargs):
    session.open(SamsungTVDownload)


def system(session, **_kwargs):
    session.open(SamsungTV)


def Plugins(**_kwargs):
    return [
        PluginDescriptor(name=_("Samsung TV Plus"), where=PluginDescriptor.WHERE_PLUGINMENU, icon=PLUGIN_ICON, description=_("Browse channels and EPG from Samsung TV Plus"), fnc=system, needsRestart=True),
        PluginDescriptor(name=_("Download Samsung TV Plus bouquet, picons and EPG"), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=Download_SamsungTV, needsRestart=True),
        PluginDescriptor(name=_("Silently download Samsung TV Plus"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart),
    ]
