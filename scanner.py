import discord
import aiohttp
import os
import requests
import json
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
BITQUERY_API_ID = os.getenv('BITQUERY_API_ID')
BITQUERY_API_SECRET = os.getenv('BITQUERY_API_SECRET')

# Initialize bot and define intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Access token for Bitquery API
bitquery_access_token = None
bitquery_token_expires_at = None

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord 🥷!')

# Format numbers for readability
def format_number(num):
    try:
        return "${:,.2f}".format(float(num))
    except (ValueError, TypeError):
        return "Unavailable"

# Function to obtain Bitquery access token
def get_bitquery_access_token():
    global bitquery_access_token, bitquery_token_expires_at
    if bitquery_access_token and bitquery_token_expires_at > datetime.utcnow():
        return bitquery_access_token

    url = "https://oauth2.bitquery.io/oauth2/token"
    payload = {
        'grant_type': 'client_credentials',
        'client_id': BITQUERY_API_ID,
        'client_secret': BITQUERY_API_SECRET,
        'scope': 'api'
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    response = requests.post(url, headers=headers, data=payload)
    
    if response.status_code == 200:
        data = response.json()
        bitquery_access_token = data["access_token"]
        bitquery_token_expires_at = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
        print("BitQuery access token obtained successfully.")
    else:
        print("Failed to obtain BitQuery access token.")
        bitquery_access_token = None

    return bitquery_access_token

# Helper function to make GraphQL requests with error handling
def graphql_request(query, variables=None):
    access_token = get_bitquery_access_token()
    if not access_token:
        print("Failed to authenticate with BitQuery.")
        return None

    url_graphql = "https://streaming.bitquery.io/eap"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    payload = json.dumps({'query': query, 'variables': variables} if variables else {'query': query})

    try:
        response = requests.post(url_graphql, headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("data", None)
    except requests.RequestException as e:
        print(f"Request error: {e}")
    except json.JSONDecodeError:
        print("Failed to parse JSON response.")
    return None

# Retrieve Helius asset data
async def get_helius_asset_data(contract_address):
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": "my-id",
        "method": "getAsset",
        "params": {
            "id": contract_address,
            "displayOptions": {
                "showFungible": True,
            }
        }
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    asset_data = await response.json()
                    return asset_data.get("result", {})
        except aiohttp.ClientError as e:
            print(f"Error fetching Helius data: {e}")
    return None

# Check migration status using BitQuery
def check_migration_status(contract_address):
    query = """
    query ($token: String) {
      Solana(network: solana) {
        Instructions(
          where: {
            Instruction: {
              Accounts: { includes: { Address: { is: $token } } },
              Program: { Name: { is: "pump" }, Method: { is: "mintTo" } }
            }
          }
        ) {
          Transaction { Signer }
        }
      }
    }
    """
    variables = {"token": contract_address}
    result = graphql_request(query, variables)
    if result:
        instructions = result.get("Solana", {}).get("Instructions", [])
        return "Detected" if instructions else "No migration detected."
    return "Unavailable"

# Check for Jito Bundle status
def check_jito_bundle(contract_address):
    query = """
    query ($token: String) {
      Solana {
        Instructions(
          where: {
            Instruction: {
              Accounts: { includes: { Address: { is: $token } } },
              Program: { Name: { is: "jito", Method: { is: "bundle" } } }
            }
          }
        ) {
          Transaction { Signer }
        }
      }
    }
    """
    variables = {"token": contract_address}
    result = graphql_request(query, variables)
    if result:
        instructions = result.get("Solana", {}).get("Instructions", [])
        return "Detected" if instructions else "No Jito Bundle detected."
    return "Unavailable"

# Check DexScreener for "Dex Paid?" status
async def get_dex_paid_status(chain_id, contract_address):
    url = f"https://api.dexscreener.com/orders/v1/{chain_id}/{contract_address}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    orders_data = await response.json()
                    if isinstance(orders_data, dict) and "orders" in orders_data:
                        for order in orders_data["orders"]:
                            if order.get("status") == "approved":
                                return "Yes"
                    return "No"
        except aiohttp.ClientError as e:
            print(f"Error checking Dex Paid status: {e}")
    return "N/A"

# Fetch latest trade info (buy/sell/total volume)
async def get_latest_trade_info(token_address):
    query = """
    query MyQuery {
      Solana {
        DEXTradeByTokens(
          where: {
            Trade: { Currency: { MintAddress: { is: "%s" } } }
          }
        ) {
          buy_volume: sum(of: Trade_Side_AmountInUSD, if: { Trade: { Side: { Type: { is: buy } } } })
          sell_volume: sum(of: Trade_Side_AmountInUSD, if: { Trade: { Side: { Type: { is: sell } } } })
          total_trade_volume: sum(of: Trade_Side_AmountInUSD)
        }
      }
    }
    """ % token_address
    result = graphql_request(query)
    if result:
        dex_data = result.get("Solana", {}).get("DEXTradeByTokens", [{}])[0]
        return {
            "buy_volume": format_number(dex_data.get("buy_volume", 0)),
            "sell_volume": format_number(dex_data.get("sell_volume", 0)),
            "total_trade_volume": format_number(dex_data.get("total_trade_volume", 0))
        }
    return {"buy_volume": "Unavailable", "sell_volume": "Unavailable", "total_trade_volume": "Unavailable"}

# Main command to fetch token information
@bot.command(name='scan')
async def fetch_token_status(ctx, contract_address: str):
    await ctx.send(f"Fetching data for contract address: {contract_address}... 🧑‍💻")

    # Retrieve data from Helius RPC
    helius_data = await get_helius_asset_data(contract_address)

    # Retrieve "Dex Paid" status
    chain_id = "solana"
    dex_paid_status = await get_dex_paid_status(chain_id, contract_address)

    # Get migration status
    migration_status = check_migration_status(contract_address)

    # Check for Jito Bundle status
    jito_bundle_status = check_jito_bundle(contract_address)

    # Get latest trade info
    trade_info = await get_latest_trade_info(contract_address)

    # Construct the embed with available data
    embed = discord.Embed(title=f"Token Info for {contract_address}", color=0x00ff00)
    if helius_data:
        token_info = helius_data.get("token_info", {})
        price_info = token_info.get("price_info", {})
        metadata = helius_data.get("content", {}).get("metadata", {})
        image_url = helius_data.get("content", {}).get("links", {}).get("image", None)
        developer_address = helius_data.get("authorities", [{}])[0].get("address", "N/A")

        # Calculate market cap with decimals adjustment
        try:
            price_per_token = float(price_info.get("price_per_token", 0))
            supply = float(token_info.get("supply", 0))
            decimals = token_info.get("decimals", 0)
            adjusted_supply = supply / (10 ** decimals) if decimals else supply
            market_cap = format_number(price_per_token * adjusted_supply) if price_per_token > 0 and adjusted_supply > 0 else "N/A"
        except (ValueError, TypeError):
            market_cap = "N/A"

        # Set embed fields with Helius data
        embed.add_field(name="🪙 Name", value=metadata.get("name", "N/A"), inline=True)
        embed.add_field(name="💠 Symbol", value=token_info.get("symbol", "N/A"), inline=True)
        embed.add_field(name="👤 Developer", value=f"[{developer_address[:8]}...](https://explorer.solana.com/address/{developer_address})", inline=True)

        # Add image if available
        if image_url:
            embed.set_thumbnail(url=image_url)
    else:
        embed.add_field(name="Error", value="No data found from Helius.", inline=False)

    # Display Dex Paid status
    embed.add_field(name="✅ Dex Paid?", value=dex_paid_status, inline=True)

    # Jito Bundle and Migration Status
    embed.add_field(name="🔄 Jito Bundle Status", value=jito_bundle_status, inline=True)
    embed.add_field(name="🔄 Migration Status", value=migration_status, inline=True)

    # Latest Trade Information
    embed.add_field(name="📈 Latest Trade Information 📈", value="━━━━━━━━━━━━━━━", inline=False)
    embed.add_field(name="🔹 Buy Volume (USD)", value=trade_info['buy_volume'], inline=True)
    embed.add_field(name="🔹 Sell Volume (USD)", value=trade_info['sell_volume'], inline=True)
    embed.add_field(name="🔹 Total Trade Volume (USD)", value=trade_info['total_trade_volume'], inline=True)

    # Market Cap
    embed.add_field(name="🏦 Market Cap", value=market_cap, inline=True)

    # Send the embed to Discord
    await ctx.send(embed=embed)

# Start the bot
bot.run(DISCORD_TOKEN)














































































































