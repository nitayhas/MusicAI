import asyncio
import discord
from discord.ext import commands
from config.settings import TOKEN, COMMAND_PREFIX
from config.logging_config import setup_logging

logger = setup_logging()

# Enable intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize bot
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user.name}')

async def load_extensions():
    await bot.load_extension('cogs.music')

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())