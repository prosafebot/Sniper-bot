import telebot
import requests
import time
import os
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
import asyncio

load_dotenv()
bot = telebot.TeleBot(os.getenv('TELEGRAM_TOKEN'))
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
wallet = Keypair.from_base58_string(PRIVATE_KEY)
client = AsyncClient("https://api.mainnet-beta.solana.com")

running = False
positions = {}
chat_id = None

def get_trending_tokens(chain='solana', limit=10):
    url = f"https://api.dexscreener.com/latest/dex/search?q={chain}&limit={limit}"
    resp = requests.get(url).json()
    return resp.get('pairs', []) if 'pairs' in resp else []

def cross_check(ca):
    # Birdeye: LP burn, insiders
    by_url = f"https://public-api.birdeye.so/defi/token_overview?address={ca}"
    by_resp = requests.get(by_url).json()
    by_data = by_resp.get('data', {})
    insiders = by_data.get('topHoldersPercentage', 1) < 0.25
    lp_burned = by_data.get('lpBurned', 0) == 100

    # GMGN: Risk, social, honeypot
    gm_url = f"https://gmgn.ai/defi/quotation/v1/tokens/{ca}?chain=sol"
    gm_resp = requests.get(gm_url).json()
    gm_data = gm_resp.get('data', {})
    honeypot = not gm_data.get('isHoneypot', True)
    social = gm_data.get('socialScore', 0) >= 50
    risk = gm_data.get('riskScore', 100) < 15

    mcap = gm_data.get('mc', 0)
    volume = gm_data.get('volume_1h', 0) > 100000

    mode = 'safe' if mcap > 1000000 else 'meme' if mcap > 50000 else None
    return mode if (insiders and lp_burned and honeypot and social and risk and volume) else None

def alpha_mentions(ca):
    return 2  # Mock; add X search later

async def buy(ca, amount_sol, mode):
    global chat_id
    bot.send_message(chat_id, f"BUYING {ca} with {amount_sol} SOL ({mode})")
    positions[ca] = {'entry': 10, 'amount': amount_sol, 'mode': mode, 'peak': 10, 'tp1_done': False, 'tp2_done': False}

async def sell(ca, pct):
    global chat_id
    bot.send_message(chat_id, f"SELLING {pct*100}% of {ca}")

async def manage_position(ca, pos):
    current = 10  # Fetch real price from Birdeye
    profit = current / pos['entry']
    pos['peak'] = max(pos['peak'], current)

    if pos['mode'] == 'safe':
        if not pos['tp1_done'] and profit >= 1.2:
            await sell(ca, 0.9)
            pos['tp1_done'] = True
        if pos['tp1_done'] and current <= pos['entry'] * 1.08:
            await sell(ca, 0.1)
        if current <= pos['entry'] * 0.9:
            await sell(ca, 1.0)
    else:  # meme
        if not pos['tp1_done'] and profit >= 1.25:
            await sell(ca, 0.5)
            pos['tp1_done'] = True
        if pos['tp1_done'] and not pos['tp2_done'] and profit >= 2.0:
            await sell(ca, 0.35)
            pos['tp2_done'] = True
        if pos['tp2_done'] and current <= pos['peak'] * 0.7:
            await sell(ca, 0.15)
        if current <= pos['entry'] * 0.9:
            await sell(ca, 1.0)

@bot.message_handler(commands=['start'])
def start(m):
    global running, chat_id
    running = True
    chat_id = m.chat.id
    bot.reply_to(m, "Sniper ON — scanning APIs...")
    asyncio.run(scan_loop())

@bot.message_handler(commands=['stop'])
def stop(m):
    global running
    running = False
    bot.reply_to(m, "Sniper STOPPED.")

@bot.message_handler(commands=['status'])
def status(m):
    pnl = sum(p['amount'] for p in positions.values())
    bot.reply_to(m, f"Positions: {len(positions)}\nPnL: +{pnl:.4f} SOL")

async def scan_loop():
    global running
    while running:
        try:
            tokens = get_trending_tokens('solana', 10)
            for t in tokens:
                ca = t['baseToken']['address']
                mode = cross_check(ca)
                if mode and alpha_mentions(ca) >= 2 and ca not in positions:
                    await buy(ca, 0.08 if mode == 'safe' else 0.02, mode)
            for ca, pos in list(positions.items()):
                await manage_position(ca, pos)
        except Exception as e:
            print(e)
        await asyncio.sleep(15)

bot.infinity_polling()
