import discord
import aiohttp
import os
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve tokens from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
HELIUS_API_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Define the intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # Required for discord.py v2 to capture message content

# Initialize the bot with the command prefix
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord 🥷!')

# Helper function to format numbers with commas
def format_number(num):
    try:
        return "{:,.2f}".format(float(num))
    except (ValueError, TypeError):
        return "N/A"

# Fetch token data using DexScreener API and contract address
async def get_dexscreener_token_data(contract_address, chain_id="solana"):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                token_data = (await response.json()).get("pairs", [])[0]

            token_name = token_data.get("baseToken", {}).get("name", "N/A")
            token_symbol = token_data.get("baseToken", {}).get("symbol", "N/A")
            logo_uri = token_data.get("baseToken", {}).get("logoURI", "N/A")

            dex_paid_url = f"https://api.dexscreener.com/orders/v1/{chain_id}/{contract_address}"
            async with session.get(dex_paid_url) as dex_paid_response:
                dex_paid_response.raise_for_status()
                order_data = await dex_paid_response.json()

            dex_paid = "No"
            if order_data and order_data[0].get("status") == "approved":
                dex_paid = "Yes"

            return {
                "base_token": token_name,
                "symbol": token_symbol,
                "price": format_number(token_data.get("priceUsd", "N/A")),
                "liquidity_usd": format_number(token_data.get("liquidity", {}).get("usd", "N/A")),
                "volume_24h": format_number(token_data.get("volume", {}).get("h24", "N/A")),
                "market_cap": format_number(token_data.get("fdv", "N/A")),
                "pair_url": token_data.get("url", "N/A"),
                "dex_paid": dex_paid
            }
    except aiohttp.ClientError as e:
        print(f"Error fetching DexScreener API: {e}")
        return None

# Fetch the total number of token holders using Solana RPC
async def fetch_token_holder_count(token_mint_address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [token_mint_address]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SOLANA_RPC_URL, json=payload) as response:
                response.raise_for_status()
                accounts_data = await response.json()
                accounts = accounts_data.get("result", {}).get("value", [])
                
                # Return the count of unique token holder accounts
                return len(accounts)
    except aiohttp.ClientError as e:
        print(f"Error fetching token largest accounts from Solana RPC: {e}")
        return 0

# Format the data for Discord message with an embed
def format_token_data_embed(data, contract_address, holder_count):
    embed = discord.Embed(title=f"Token Info for {contract_address}", color=0x00ff00)
    embed.add_field(name="🪙 Token", value=data["base_token"], inline=True)
    embed.add_field(name="💠 Symbol", value=data["symbol"], inline=True)
    embed.add_field(name="💵 Price (USD)", value=f'${data["price"]}', inline=True)
    embed.add_field(name="💧 Liquidity (USD)", value=f'${data["liquidity_usd"]}', inline=True)
    embed.add_field(name="📈 Market Cap (FDV)", value=f'${data["market_cap"]}', inline=True)
    embed.add_field(name="🔄 24h Volume", value=f'${data["volume_24h"]}', inline=True)
    embed.add_field(name="🌐 Pair URL", value=data["pair_url"], inline=False)
    embed.add_field(name="✅ Dex Paid?", value=data["dex_paid"], inline=True)
    embed.add_field(name="👥 Token Holders", value=f'{holder_count} wallets', inline=True)
    return embed

# Command to fetch token status
@bot.command(name='token')
async def fetch_token_status(ctx, contract_address: str):
    await ctx.send(f"Fetching token data for contract address: {contract_address}... 🧑‍💻")

    # Fetch DexScreener token data
    token_data = await get_dexscreener_token_data(contract_address)

    # Fetch accurate token holder count from Solana RPC
    holder_count = await fetch_token_holder_count(contract_address)

    if token_data:
        # Format and send the message with accurate data
        embed_message = format_token_data_embed(token_data, contract_address, holder_count)
        await ctx.send(embed=embed_message)
    else:
        await ctx.send(f"Error fetching data for contract address: {contract_address} 🛑")

# Start the bot
bot.run(DISCORD_TOKEN)































