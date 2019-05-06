# Lorewalker Cho is a Discord bot that plays WoW-inspired trivia games.
# Copyright (C) 2019  Walter Kuppens

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Contains the Discord client class for Cho."""

import asyncio
import logging
import discord
import cho

from game_state import GameState

SHORT_WAIT_SECS = 5
LONG_WAIT_SECS = 10

LOGGER = logging.getLogger("cho")


class ChoClient(discord.Client):
    """Discord client wrapper that uses functionality from cho.py."""

    def __init__(self, engine):
        """Initializes the ChoClient with a sqlalchemy connection pool.

        :param e engine: SQLAlchemy engine to make queries with.
        :type e: sqlalchemy.engine.Engine
        :rtype: ChoClient
        :return:
        """

        super().__init__()

        self.engine = engine
        self.guild_configs = {}
        self.active_games = {}

    async def on_ready(self):
        """Called when the bot has successfully connected to Discord."""

        LOGGER.info("Client logged in as \"%s\"", self.user)

    async def on_message(self, message):
        """Called whenever the bot receives a message from Discord.

        :param m message:
        :type m: discord.message.Message
        """

        LOGGER.info("Message from \"%s\": %s", message.author, message.content)

        # Don't accept direct messages at this time. I might circle back later
        # and add support for private trivia sessions, but it's not a priority
        # for me right now.
        if message.guild is None:
            await message.channel.send(
                "Oh hello there, I don't currently do private trivia "
                "sessions. If you want to start a game, call for me in a "
                "Discord server."
            )
            return

        # TODO: Get prefix from the configuration.
        prefix = "!"
        game_in_progress = message.guild.id in self.active_games

        if cho.is_command(message, prefix):
            self.handle_command(message)
        elif game_in_progress and cho.is_message_from_trivia_channel(message):
            self.process_answer(message)

    async def handle_command(self, message):
        """Called when a Cho command is received from a user.

        :param m message:
        :type m: discord.message.Message
        """

        if not cho.is_message_from_trivia_channel(message):
            await message.channel.send(
                "Sorry, I can't be summoned into this channel. Please go "
                "to the trivia channel for this server."
            )
            return

        args = message.content.split()

        if len(args) < 2:
            await message.channel.send(
                "You didn't specify a command. If you want to "
                "start a game use the \"start\" command."
            )
            return

        if args[1].lower() == "start":
            self.handle_start_command(message)
        else:
            await message.channel.send(
                "I'm afraid I don't know that command. If you want to "
                "start a game use the \"start\" command."
            )

    async def handle_start_command(self, message):
        """Executes the start command for Cho.

        :param m message:
        :type m: discord.message.Message
        """

        if message.guild.id in self.active_games:
            await message.channel.send(
                "A game is already active in the trivia channel. If you "
                "want to participate please go in there."
            )
            return

        LOGGER.info(
            "Starting game in guild %s, requested by %s",
            message.guild.id, message.author
        )
        await message.channel.send(
            "Okay I'm starting a game. Don't expect me to go easy"
        )
        self.start_game(message.channel)

    async def start_game(self, channel):
        """Starts a new trivia game.

        :param c channel:
        :type c: discord.channel.Channel
        """

        await asyncio.sleep(SHORT_WAIT_SECS)
        self.ask_question(channel, GameState())

    async def process_answer(self, message):
        """Called when an answer is received from a user.

        :param m message:
        :type m: discord.message.Message
        """

        active_game = self.active_games[message.guild.id]

        # Don't process the answer if the bot is currently in-between asking
        # questions. Without this multiple people can get the answer right
        # rather than just the first person.
        if not active_game.waiting:
            return

        if active_game.check_answer(message.content):
            active_game.waiting = False
            active_game.bump_score(user_id)
            active_game.step()

            user_id = message.user.id
            question = active_game.get_question()

            await message.channel.send(
                "Correct, <@{user_id}>! The answer is {answer}".format(
                    user_id=user_id,
                    answer=question["answers"][0],
                ),
            )
            await asyncio.sleep(SHORT_WAIT_SECS)
            self.ask_question(message.channel, active_game)

    async def ask_question(self, channel, active_game):
        """Asks a trivia question in a Discord channel.

        :param c channel:
        :param GameState active_game:
        :type c: discord.channel.Channel
        """

        if active_game.complete:
            await self.finish_game(channel)
            return

        question = active_game.get_question()
        last_correct_answers_total = active_game.correct_answers_total

        active_game.waiting = True
        await channel.send(question["text"])
        await asyncio.sleep(LONG_WAIT_SECS)

        # If the correct answer total was not incrememnted, that means that no
        # one answered the question correctly. Give them the answer if so.
        if last_correct_answers_total == active_game.correct_answers_total:
            active_game.waiting = False
            active_game.step()

            await channel.send(
                "The correct answer was \"{answer}\"".format(
                    answer=question["answers"][0],
                ),
            )
            await asyncio.sleep(SHORT_WAIT_SECS)
            self.ask_question(channel, active_game)

    async def finish_game(self, channel):
        """Outputs the scoreboard and announces the winner of a game.

        :param c channel:
        :type c: discord.channel.Channel
        """

        await channel.send(
            "Alright we're out of questions. The winners are:",
        )
