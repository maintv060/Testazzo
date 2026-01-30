# Import necessary modules
from discord.ext import commands

# Define command prefix and intents
PREFIX = '!'  
INTENTS = commands.Intents.default()  

# Initialize bot without help command
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)