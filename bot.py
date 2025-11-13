import telebot
import requests
import time
import os
import asyncio
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair

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
    try:
        by_url = f"https://public-api.birdeye.so/defi/token_overview?address={ca}"
        by_resp = requests.get(by_url, timeout=5).json()
        by_data = by_resp.get('data', {})
        insiders = by_data.get('topHoldersPercentage', 1) < 0.25
        lp_burned = by_data.get('lpBurned', 0) == 100

        gm_url = f"https://gmgn.ai/defi/quotation/v1/tokens/{ca}?chain=sol"
        gm_resp = requests.get(gm_url, timeout=5).json()
        gm_data = gm_resp.get('data', {})
        honeypot = not gm_data.get('isHoneypot', True)
        social = gm_data.get('socialScore', 0) >= 50
        risk = gm_data.get('riskScore', 100) < 15
        mcap = gm_data.get('mc', 0)
        volume = gm_data.get('volume_1h', 0) > 100000

        mode = 'safe' if mcap > 1000000 else 'meme' if mcap > 50000 else None
        return mode if (insiders and lp_burned and honeypot and social and risk and volume) else None
    except:
        return None

def alpha_mentions(ca):
    return 2  # Replace later

async def get_price(ca):
    try:
        url = f"https://public-api.birdeye.so/defi/price?address={ca}"
        resp = requests.get(url, timeout=5).json()
        return resp['data']['value']
    except:
        return 10

async def buy(ca, amount_sol, mode):
    global chat_id
    price = await get_price(ca)
    bot.send_message(chat_id, f"BUYING {ca[:6]}...{ca[-4:]} with {amount_sol} SOL ({mode})\nEntry: ${price:.6f}")
    positions[ca] = {
        'entry': price,
        'amount': amount_sol,
        'mode': mode,
        'peak': price,
        'tp1_done': False,
        'tp2_done': False
    }

async def sell(ca, pct):
    global chat_id
    pos = positions[ca]
    price = await get_price(ca)
    profit = price / pos['entry']
    bot.send_message(chat_id, f"SELLING {pct*100:.0f}% of {ca[:6]}...{ca[-4:]}\nPrice: ${price:.6f} | PnL: {(profit-1)*100:+.2f}%")
    if pct == 1.0:
        del positions[ca]

async def manage_position(ca, pos):
    current = await get_price(ca)
    profit = current / pos['entry']
    pos['peak'] = max(pos['peak'], current)

    if pos['mode'] == 'safe':
        if not pos['tp1_done'] and profit >= 1.2:
            await sell(ca, 0.9); pos['tp1_done'] = True
        elif pos['tp1_done'] and current <= pos['entry'] * 1.08:
            await sell(ca, 0.1)
        elif current <= pos['entry'] * 0.9:
            await sell(ca, 1.0)
    else:
        if not pos['tp1_done'] and profit >= 1.25:
            await sell(ca, 0.5); pos['tp1_done'] = True
        elif pos['tp1_done'] and not pos['tp2_done'] and profit >= 2.0:
            await sell(ca, 0.35); pos['tp2_done'] = True
        elif pos['tp2_done'] and current <= pos['peak'] * 0.7:
            await sell(ca, 0.15)
        elif current <= pos['entry'] * 0.9:
            await sell(ca, 1.0)

@bot.message_handler(commands=['start'])
def start(m):
    global running, chat_id
    if running:
        bot.reply_to(m, "Sniper already running!")
        return
    running = True
    chat_id = m.chat.id
    bot.reply_to(m, "Sniper ON — scanning APIs every 15s...")
    asyncio.create_task(scan_loop())

@bot.message_handler(commands=['stop'])
def stop(m):
    global running
    running = False
    bot.reply_to(m, "Sniper STOPPED.")

@bot.message_handler(commands=['status'])
def status(m):
    if not positions:
        bot.reply_to(m, "No open positions.\nPnL: +0.0000 SOL")
        return
    msg = f"Open: {len(positions)}\n"
    for ca, p in positions.items():
        price = asyncio.run(get_price(ca))
        pnl = (price / p['entry'] - 1) * 100
        msg += f"• {ca[:6]}...{ca[-4:]} | {p['amount']} SOL | {p['mode']} | PnL: {pnl:+.2f}%\n"
    bot.reply_to(m, msg)

async def scan_loop():
    global running
    while running:
        try:
            tokens = get_trending_tokens('solana', 10)
            for t in tokens:
                ca = t['baseToken']['address']
                if ca in positions: continue
                mode = cross_check(ca)
                if mode and alpha_mentions(ca) >= 2:
                    await buy(ca, 0.08 if mode == 'safe' else 0.02, mode)
            for ca in list(positions.keys()):
                if ca in positions:
                    await manage_position(ca, positions[ca])
        except Exception as e:
            print(f"Scan error: {e}")
        await asyncio.sleep(15)

if __name__ == "__main__":
    print("Starting Telegram Sniper Bot...")
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"Bot crashed: {e}")
        time.sleep(5)
        bot.infinity_polling()
