###
# Copyright (c) 2002-2004, Jeremiah Fincher
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import re

import config

import supybot.conf as conf
import supybot.utils as utils
from supybot.commands import *
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.schedule as schedule
import supybot.callbacks as callbacks

class Services(callbacks.Plugin):
    """This plugin handles dealing with Services on networks that provide them.
    Basically, you should use the "password" command to tell the bot a nick to
    identify with and what password to use to identify with that nick.  You can
    use the password command multiple times if your bot has multiple nicks
    registered.  Also, be sure to configure the NickServ and ChanServ
    configuration variables to match the NickServ and ChanServ nicks on your
    network.  Other commands such as identify, op, etc. should not be
    necessary if the bot is properly configured."""
    def __init__(self, irc):
        self.__parent = super(Services, self)
        self.__parent.__init__(irc)
        for nick in self.registryValue('nicks'):
            config.registerNick(nick)
        self.reset()

    def reset(self):
        self.channels = []
        self.sentGhost = False
        self.identified = False
        self.waitingJoins = []

    def outFilter(self, irc, msg):
        if msg.command == 'JOIN':
            if not self.identified:
                if self.registryValue('noJoinsUntilIdentified'):
                    self.log.info('Holding JOIN to %s until identified.',
                                  msg.args[0])
                    self.waitingJoins.append(msg)
                    return None
        return msg

    def _getNick(self):
        return conf.supybot.nick()

##     def _getNickServ(self, network):
##         return self.registryValue('NickServ', network)

    def _getNickServPassword(self, nick):
        # This should later be nick-specific.
        assert nick in self.registryValue('nicks')
        return self.registryValue('NickServ.password.%s' % nick)

    def _setNickServPassword(self, nick, password):
        # This also should be nick-specific.
        assert nick in self.registryValue('nicks')
        self.setRegistryValue('NickServ.password.%s' % nick, password)

    def _doIdentify(self, irc, nick=None):
        if nick is None:
            nick = self._getNick()
        if nick not in self.registryValue('nicks'):
            return
        nickserv = self.registryValue('NickServ')
        password = self._getNickServPassword(nick)
        if not nickserv or not password:
            s = 'Tried to identify without a NickServ or password set.'
            self.log.warning(s)
            return
        assert ircutils.strEqual(irc.nick, nick), \
               'Identifying with not normal nick.'
        self.log.info('Sending identify (current nick: %s)', irc.nick)
        identify = 'IDENTIFY %s' % password
        # It's important that this next statement is irc.sendMsg, not
        # irc.queueMsg.  We want this message to get through before any
        # JOIN messages also being sent on 376.
        irc.sendMsg(ircmsgs.privmsg(nickserv, identify))

    def _doGhost(self, irc, nick=None):
        if nick is None:
            nick = self._getNick()
        if nick not in self.registryValue('nicks'):
            return
        nickserv = self.registryValue('NickServ')
        password = self._getNickServPassword(nick)
        if not nickserv or not password:
            s = 'Tried to ghost without a NickServ or password set.'
            self.log.warning(s)
            return
        if self.sentGhost:
            self.log.warning('Refusing to send GHOST twice.')
        elif not password:
            self.log.warning('Not ghosting: no password set.')
            return
        else:
            self.log.info('Sending ghost (current nick: %s; ghosting: %s)',
                          irc.nick, nick)
            ghost = 'GHOST %s %s' % (nick, password)
            # Ditto about the sendMsg (see _doIdentify).
            irc.sendMsg(ircmsgs.privmsg(nickserv, ghost))
            self.sentGhost = True

    def __call__(self, irc, msg):
        disabled = self.registryValue('disabledNetworks')
        if irc.network in disabled or \
           irc.state.supported.get('NETWORK', '') in disabled:
            return
        self.__parent.__call__(irc, msg)
        nick = self._getNick()
        if nick not in self.registryValue('nicks'):
            return
        nickserv = self.registryValue('NickServ')
        password = self._getNickServPassword(nick)
        if nick and nickserv and password and \
           not ircutils.strEqual(nick, irc.nick):
            if irc.afterConnect and not self.sentGhost:
                if nick in irc.state.nicksToHostmasks:
                    self._doGhost(irc)
                else:
                    irc.sendMsg(ircmsgs.nick(nick)) # 433 is handled elsewhere.

    def do001(self, irc, msg):
        # New connection, make sure sentGhost is False.
        self.sentGhost = False

    def do376(self, irc, msg):
        nick = self._getNick()
        if nick not in self.registryValue('nicks'):
            return
        nickserv = self.registryValue('NickServ')
        if not nickserv:
            self.log.warning('NickServ is unset, cannot identify.')
            return
        password = self._getNickServPassword(nick)
        if not password:
            self.log.warning('Password for %s is unset, cannot identify.',nick)
            return
        if not nick:
            self.log.warning('Cannot identify without a nick being set.  '
                             'Set supybot.plugins.Services.nick.')
            return
        if ircutils.strEqual(irc.nick, nick):
            self._doIdentify(irc)
        else:
            self._doGhost(irc)
    do422 = do377 = do376

    def do433(self, irc, msg):
        nick = self._getNick()
        if nick not in self.registryValue('nicks'):
            return
        if nick and irc.afterConnect:
            password = self._getNickServPassword(nick)
            if not password:
                return
            self._doGhost(irc)

    def do515(self, irc, msg):
        # Can't join this channel, it's +r (we must be identified).
        self.channels.append(msg.args[1])

    def doNick(self, irc, msg):
        nick = self._getNick()
        if ircutils.strEqual(msg.args[0], irc.nick) and \
           ircutils.strEqual(irc.nick, nick):
            self._doIdentify(irc)
        elif ircutils.strEqual(msg.nick, nick):
            irc.sendMsg(ircmsgs.nick(nick))

    def _ghosted(self, s):
        nick = self._getNick()
        lowered = s.lower()
        return bool('killed' in lowered and (nick in s or 'ghost' in lowered))

    def doNotice(self, irc, msg):
        if irc.afterConnect:
            nickserv = self.registryValue('NickServ')
            chanserv = self.registryValue('ChanServ')
            if nickserv and ircutils.strEqual(msg.nick, nickserv):
                self.doNickservNotice(irc, msg)
            elif chanserv and ircutils.strEqual(msg.nick, chanserv):
                self.doChanservNotice(irc, msg)

    _chanRe = re.compile('\x02(.*?)\x02')
    def doChanservNotice(self, irc, msg):
        s = msg.args[1].lower()
        channel = None
        m = self._chanRe.search(s)
        networkGroup = conf.supybot.networks.get(irc.network)
        if m is not None:
            channel = m.group(1)
        if 'all bans' in s or 'unbanned from' in s:
            # All bans removed (freenode)
            # You have been unbanned from (oftc)
            irc.sendMsg(networkGroup.channels.join(channel))
        elif 'isn\'t registered' in s:
            self.log.warning('Received "%s isn\'t registered" from ChanServ',
                             channel)
        elif 'this channel has been registered' in s:
            self.log.debug('Got "Registered channel" from ChanServ.')
        elif 'already opped' in s:
            # This shouldn't happen, Services.op should refuse to run if
            # we already have ops.
            self.log.debug('Got "Already opped" from ChanServ.')
        elif 'access level' in s and 'is required' in s:
            self.log.warning('Got "Access level required" from ChanServ.')
        elif 'inviting' in s:
            self.log.debug('Got "Inviting to channel" from ChanServ.')
        else:
            self.log.warning('Got unexpected notice from ChanServ: %r.', msg)

    def doNickservNotice(self, irc, msg):
        nick = self._getNick()
        s = ircutils.stripFormatting(msg.args[1].lower())
        networkGroup = conf.supybot.networks.get(irc.network)
        if 'incorrect' in s or 'denied' in s:
            log = 'Received "Password Incorrect" from NickServ.  ' \
                  'Resetting password to empty.'
            self.log.warning(log)
            self.sentGhost = False
            self._setNickServPassword(nick, '')
        elif self._ghosted(s):
            self.log.info('Received "GHOST succeeded" from NickServ.')
            self.sentGhost = False
            self.identified = False
            irc.queueMsg(ircmsgs.nick(nick))
        elif 'currently' in s and 'isn\'t' in s or 'is not' in s:
            # The nick isn't online, let's change our nick to it.
            self.sentGhost = False
            irc.queueMsg(ircmsgs.nick(nick))
        elif ('owned by someone else' in s) or \
             ('nickname is registered and protected' in s) or \
             ('nick belongs to another user' in s):
            # freenode, arstechnica, chatjunkies
            # oftc, zirc.org
            # sorcery
            self.log.info('Received "Registered nick" from NickServ.')
        elif '/msg' in s and 'id' in s and 'password' in s:
            # Usage info for identify command; ignore.
            self.log.debug('Got usage info for identify command.')
        elif ('please choose a different nick' in s): # oftc, part 3
            # This is a catch-all for redundant messages from nickserv.
            pass
        elif ('now recognized' in s) or \
             ('now identified' in s):
            # freenode, oftc, arstechnica, zirc, ....
            # sorcery
            self.log.info('Received "Password accepted" from NickServ.')
            self.identified = True
            for channel in irc.state.channels.keys():
                self.checkPrivileges(irc, channel)
            for channel in self.channels:
                irc.queueMsg(networkGroup.channels.join(channel))
            if self.waitingJoins:
                for m in self.waitingJoins:
                    irc.sendMsg(m)
                self.waitingJoins = []
        elif 'not yet authenticated' in s:
            # zirc.org has this, it requires an auth code.
            email = s.split()[-1]
            self.log.warning('Received "Nick not yet authenticated" from '
                             'NickServ.  Check email at %s and send the auth '
                             'command to NickServ.', email)
        else:
            self.log.debug('Unexpected notice from NickServ: %q.', s)

    def checkPrivileges(self, irc, channel):
        chanserv = self.registryValue('ChanServ')
        if chanserv and self.registryValue('ChanServ.op', channel):
            if irc.nick not in irc.state.channels[channel].ops:
                self.log.info('Requesting op from %s in %s.',
                              chanserv, channel)
                irc.sendMsg(ircmsgs.privmsg(chanserv, 'op %s' % channel))
        if chanserv and self.registryValue('ChanServ.halfop', channel):
            if irc.nick not in irc.state.channels[channel].halfops:
                self.log.info('Requesting halfop from %s in %s.',
                              chanserv, channel)
                irc.sendMsg(ircmsgs.privmsg(chanserv, 'halfop %s' % channel))
        if chanserv and self.registryValue('ChanServ.voice', channel):
            if irc.nick not in irc.state.channels[channel].voices:
                self.log.info('Requesting voice from %s in %s.',
                              chanserv, channel)
                irc.sendMsg(ircmsgs.privmsg(chanserv, 'voice %s' % channel))

    def doMode(self, irc, msg):
        chanserv = self.registryValue('ChanServ')
        if ircutils.strEqual(msg.nick, chanserv):
            channel = msg.args[0]
            if len(msg.args) == 3:
                if ircutils.strEqual(msg.args[2], irc.nick):
                    mode = msg.args[1]
                    info = self.log.info
                    if mode == '+o':
                        info('Received op from ChanServ in %s.', channel)
                    elif mode == '+h':
                        info('Received halfop from ChanServ in %s.', channel)
                    elif mode == '+v':
                        info('Received voice from ChanServ in %s.', channel)

    def do366(self, irc, msg): # End of /NAMES list; finished joining a channel
        if self.identified:
            channel = msg.args[1] # nick is msg.args[0].
            self.checkPrivileges(irc, channel)

    def _chanservCommand(self, irc, channel, command, log=False):
        chanserv = self.registryValue('ChanServ')
        if chanserv:
            msg = ircmsgs.privmsg(chanserv,
                                  ' '.join([command, channel, irc.nick]))
            irc.sendMsg(msg)
        else:
            if log:
                self.log.warning('Unable to send %s command to ChanServ, '
                                 'you must set '
                                 'supybot.plugins.Services.ChanServ before '
                                 'I can send commands to ChanServ.', command)
            else:
                irc.error('You must set supybot.plugins.Services.ChanServ '
                          'before I\'m able to do get voiced.', Raise=True)

    def op(self, irc, msg, args, channel):
        """[<channel>]

        Attempts to get opped by ChanServ in <channel>.  <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        if irc.nick in irc.state.channels[channel].ops:
            irc.error(format('I\'m already opped in %s.', channel))
        else:
            self._chanservCommand(irc, channel, 'op')
    op = wrap(op, [('checkChannelCapability', 'op'), 'inChannel'])

    def voice(self, irc, msg, args, channel):
        """[<channel>]

        Attempts to get voiced by ChanServ in <channel>.  <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        if irc.nick in irc.state.channels[channel].voices:
            irc.error(format('I\'m already voiced in %s.', channel))
        else:
            self._chanservCommand(irc, channel, 'voice')
    voice = wrap(voice, [('checkChannelCapability', 'op'), 'inChannel'])

    def do474(self, irc, msg):
        channel = msg.args[1]
        self.log.info('Banned from %s, attempting ChanServ unban.', channel)
        self._chanservCommand(irc, channel, 'unban', log=True)
        # Success log in doChanservNotice.

    def unban(self, irc, msg, args, channel):
        """[<channel>]

        Attempts to get unbanned by ChanServ in <channel>.  <channel> is only
        necessary if the message isn't sent in the channel itself, but chances
        are, if you need this command, you're not sending it in the channel
        itself.
        """
        self._chanservCommand(irc, channel, 'unban')
        irc.replySuccess()
    unban = wrap(unban, [('checkChannelCapability', 'op')])

    def do473(self, irc, msg):
        channel = msg.args[1]
        self.log.info('%s is +i, attempting ChanServ invite.', channel)
        self._chanservCommand(irc, channel, 'invite', log=True)

    def invite(self, irc, msg, args, channel):
        """[<channel>]

        Attempts to get invited by ChanServ to <channel>.  <channel> is only
        necessary if the message isn't sent in the channel itself, but chances
        are, if you need this command, you're not sending it in the channel
        itself.
        """
        self._chanservCommand(irc, channel, 'invite')
        irc.replySuccess()
    invite = wrap(invite, [('checkChannelCapability', 'op'), 'inChannel'])

    def doInvite(self, irc, msg):
        if ircutils.strEqual(msg.nick, self.registryValue('ChanServ')):
            channel = msg.args[1]
            networkGroup = conf.supybot.networks.get(irc.network)
            self.log.info('Joining %s, invited by ChanServ.', channel)
            irc.queueMsg(networkGroup.channels.join(channel))

    def identify(self, irc, msg, args):
        """takes no arguments

        Identifies with NickServ using the current nick.
        """
        if self.registryValue('NickServ'):
            if irc.nick in self.registryValue('nicks'):
                self._doIdentify(irc, irc.nick)
                irc.replySuccess()
            else:
                irc.error('I don\'t have a configured password for '
                          'my current nick.')
        else:
            irc.error('You must set supybot.plugins.Services.NickServ before '
                      'I\'m able to do identify.')
    identify = wrap(identify, [('checkCapability', 'admin')])

    def ghost(self, irc, msg, args, nick):
        """[<nick>]

        Ghosts the bot's given nick and takes it.  If no nick is given,
        ghosts the bot's configured nick and takes it.
        """
        if self.registryValue('NickServ'):
            if not nick:
                nick = self._getNick()
            if ircutils.strEqual(nick, irc.nick):
                irc.error('I cowardly refuse to ghost myself.')
            else:
                self._doGhost(irc, nick=nick)
                irc.replySuccess()
        else:
            irc.error('You must set supybot.plugins.Services.NickServ before '
                      'I\'m able to ghost a nick.')
    ghost = wrap(ghost, [('checkCapability', 'admin'), additional('nick')])

    def password(self, irc, msg, args, nick, password):
        """<nick> [<password>]

        Sets the NickServ password for <nick> to <password>.  If <password> is
        not given, removes <nick> from the configured nicks.
        """
        if not password:
            try:
                self.registryValue('nicks').remove(nick)
                irc.replySuccess()
            except KeyError:
                irc.error('That nick was not configured with a password.')
                return
        else:
            self.registryValue('nicks').add(nick)
            config.registerNick(nick, password)
            irc.replySuccess()
    password = wrap(password, [('checkCapability', 'admin'),
                                'private', 'nick', 'text'])

    def nicks(self, irc, msg, args):
        """takes no arguments

        Returns the nicks that this plugin is configured to identify and ghost
        with.
        """
        L = list(self.registryValue('nicks'))
        if L:
            utils.sortBy(ircutils.toLower, L)
            irc.reply(format('%L', L))
        else:
            irc.reply('I\'m not currently configured for any nicks.')
    nicks = wrap(nicks, [('checkCapability', 'admin')])


Class = Services

# vim:set shiftwidth=4 tabstop=8 expandtab textwidth=78: