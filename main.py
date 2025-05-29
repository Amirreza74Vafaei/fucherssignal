import ccxt
import pandas as pd
import ta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import time
from config import TELEGRAM_TOKEN, CHAT_ID, SYMBOLS, TIMEFRAME
import requests
import asyncio
from telegram.constants import ParseMode
import matplotlib.pyplot as plt
import io
import matplotlib.dates as mdates

exchange = ccxt.binance({'options': {'defaultType': 'future'}})
TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

def fetch_data(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=150)
    df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
    return df

def get_support_resistance(df, window=20):
    support = df['low'].tail(window).min()
    resistance = df['high'].tail(window).max()
    return support, resistance

def analyze(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['ema_20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
    df['ema_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    df['sma_20'] = ta.trend.SMAIndicator(df['close'], window=20).sma_indicator()
    last = df.iloc[-1]
    prev = df.iloc[-2]
    support, resistance = get_support_resistance(df)
    signal = "سیگنال خنثی (Hold)"
    explanation = []
    price = last['close']
    volume = last['volume']
    sma20 = last['sma_20']
    recent = df.tail(20)
    max_vol_idx = recent['volume'].idxmax()
    liquidity_price = recent.loc[max_vol_idx, 'close']
    if last['rsi'] < 30 and prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal'] and last['ema_20'] > last['ema_50']:
        signal = "سیگنال ورود (Long)"
        explanation.append("RSI زیر ۳۰ است (اشباع فروش). MACD کراس به بالا دارد. EMA20 بالای EMA50 است.")
    elif last['rsi'] > 70 and prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal'] and last['ema_20'] < last['ema_50']:
        signal = "سیگنال خروج (Short)"
        explanation.append("RSI بالای ۷۰ است (اشباع خرید). MACD کراس به پایین دارد. EMA20 زیر EMA50 است.")
    else:
        explanation.append("شرایط ورود یا خروج قوی مشاهده نشد. منتظر بمانید.")
    explanation.append(f"قیمت فعلی: {price:.4f}")
    explanation.append(f"حجم خرید (آخرین کندل): {volume:.2f}")
    explanation.append(f"SMA20: {sma20:.2f}")
    explanation.append(f"منطقه لیکوییدیتی (بیشترین حجم ۲۰ کندل اخیر): {liquidity_price:.2f}")
    explanation.append(f"حمایت مهم: {support:.2f}")
    explanation.append(f"مقاومت مهم: {resistance:.2f}")
    explanation.append(f"RSI: {last['rsi']:.2f} | MACD: {last['macd']:.2f} | EMA20: {last['ema_20']:.2f} | EMA50: {last['ema_50']:.2f}")
    return signal, "\n".join(explanation)

async def send_long_message(bot, chat_id, text, symbol="گزارش"):
    max_length = 4000
    if len(text) <= max_length:
        await bot.send_message(chat_id=chat_id, text=f"{symbol} ({TIMEFRAME}): {text}")
    else:
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        for idx, part in enumerate(parts):
            await bot.send_message(chat_id=chat_id, text=f"{symbol} ({TIMEFRAME}) - بخش {idx+1}:\n{part}")

def fetch_news():
    API_KEY = 'abb4f276e15860b14ef352bc376f0f4b38c8f231'
    url = f'https://cryptopanic.com/api/v1/posts/?auth_token={API_KEY}&public=true'
    try:
        response = requests.get(url)
        data = response.json()
        news_list = []
        for item in data['results'][:5]:
            news_list.append(f"- {item['title']}")
        return "\n".join(news_list)
    except Exception as e:
        return "خطا در دریافت اخبار"

def fetch_tradingview_ideas():
    return "ایده‌های جدید تحلیل‌گران را در https://www.tradingview.com/ideas/btcusd/ ببینید."

def generate_chart(df, symbol, timeframe):
    df['datetime'] = pd.to_datetime(df['time'], unit='ms')
    plt.figure(figsize=(10, 5))
    plt.plot(df['datetime'], df['close'], label='Close Price', color='blue')
    plt.title(f'{symbol} / USDT - {timeframe}')
    plt.xlabel('Time')
    plt.ylabel('Price (USDT)')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))
    plt.gcf().autofmt_xdate()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 گزارش کلی", callback_data='full_report')],
        [InlineKeyboardButton("🪙 لیست ارزها", callback_data='list_coins')],
    ]
    for symbol in SYMBOLS:
        keyboard.append([InlineKeyboardButton(symbol, callback_data=f'select_timeframe_{symbol}')])
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_menu(symbol):
    keyboard = []
    for tf in TIMEFRAMES:
        keyboard.append([InlineKeyboardButton(tf, callback_data=f'signal_{symbol}_{tf}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = get_main_menu()
    welcome_text = (
        "👋 *به ربات تحلیل ارز دیجیتال خوش آمدید!*\n"
        "این ربات به شما سیگنال و تحلیل بازار کریپتو را به صورت خودکار ارائه می‌دهد.\n"
        "یکی از گزینه‌ها را از منو انتخاب کنید یا دستور /help را برای راهنما بزنید."
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*راهنمای ربات تحلیل ارز دیجیتال*\n"
        "\nدستورات اصلی:\n"
        "- /start : نمایش منوی اصلی\n"
        "- /help : نمایش همین راهنما\n"
        "\nاز منوی زیر پیام خوش‌آمدگویی می‌توانید گزارش کلی، لیست ارزها یا سیگنال هر ارز را دریافت کنید.\n"
        "\n*امکانات ویژه:*\n"
        "- ارسال سیگنال‌های خرید/فروش\n"
        "- تحلیل تکنیکال با اندیکاتورهای مختلف\n"
        "- دریافت اخبار مهم و ایده‌های تحلیل‌گران\n"
        "\nبرای انتخاب تایم‌فریم و امکانات بیشتر به‌زودی آپدیت خواهد شد!\n"
        "\n[سازنده: @YourUsername](https://t.me/YourUsername)"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'full_report':
        report = []
        for symbol in SYMBOLS:
            try:
                df = fetch_data(symbol)
                signal, explanation = analyze(df)
                report.append(f"*{symbol}*: {signal}\n{explanation}")
                time.sleep(1)
            except Exception as e:
                report.append(f"{symbol}: خطا در دریافت داده")
        news = fetch_news()
        ideas = fetch_tradingview_ideas()
        full_report = (
            "📊 *گزارش کامل تحلیل:*\n\n"
            + "\n\n".join(report)
            + "\n\n📰 *اخبار مهم:*\n"
            + news
            + "\n\n💡 *تحلیل تحلیل‌گران:*\n"
            + ideas
        )
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='back_to_menu')]])
        await query.edit_message_text(full_report, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif data == 'list_coins':
        coins = (
            "🪙 *۵ میم‌کوین برتر:*\n"
            "- DOGE/USDT\n- SHIB/USDT\n- PEPE/USDT\n- FLOKI/USDT\n- BONK/USDT\n\n"
            "🪙 *۵ آلت‌کوین برتر:*\n"
            "- ETH/USDT\n- BNB/USDT\n- SOL/USDT\n- XRP/USDT\n- ADA/USDT"
        )
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='back_to_menu')]])
        await query.edit_message_text(coins, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif data.startswith('select_timeframe_'):
        symbol = data.replace('select_timeframe_', '')
        reply_markup = get_timeframe_menu(symbol)
        await query.edit_message_text(f"تایم‌فریم مورد نظر را برای {symbol} انتخاب کنید:", reply_markup=reply_markup)
    elif data.startswith('signal_'):
        try:
            _, symbol, tf = data.split('_', 2)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=150)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            signal, explanation = analyze(df)
            text = f"*{symbol}* ({tf}): {signal}\n{explanation}"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📈 مشاهده چارت", callback_data=f'chart_{symbol}_{tf}')], [InlineKeyboardButton("🔙 بازگشت به منو", callback_data='back_to_menu')]])
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            text = f"{symbol}: خطا در دریافت داده"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='back_to_menu')]])
            await query.edit_message_text(text, reply_markup=reply_markup)
    elif data.startswith('chart_'):
        try:
            _, symbol, tf = data.split('_', 2)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=150)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            buf = generate_chart(df, symbol, tf)
            msg = await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=buf,
                caption=f"چارت قیمت {symbol} / USDT ({tf})",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['last_chart_msg_id'] = msg.message_id
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat.id, text="خطا در دریافت یا رسم چارت.")
    elif data == 'back_to_menu':
        last_chart_msg_id = context.user_data.get('last_chart_msg_id')
        if last_chart_msg_id:
            try:
                await context.bot.delete_message(chat_id=query.message.chat.id, message_id=last_chart_msg_id)
            except Exception:
                pass
            context.user_data['last_chart_msg_id'] = None
        reply_markup = get_main_menu()
        await query.edit_message_text('به منوی اصلی بازگشتید. یکی از گزینه‌ها را انتخاب کنید:', reply_markup=reply_markup)
    else:
        await query.edit_message_text('دستور نامعتبر است.', reply_markup=get_main_menu())

async def hourly_report(context: ContextTypes.DEFAULT_TYPE):
    report = []
    for symbol in SYMBOLS:
        try:
            df = fetch_data(symbol)
            signal, explanation = analyze(df)
            report.append(f"{symbol}: {signal}\n{explanation}")
            time.sleep(2)
        except Exception as e:
            report.append(f"{symbol}: خطا در دریافت داده")
    news = fetch_news()
    ideas = fetch_tradingview_ideas()
    full_report = (
        "📊 گزارش کامل تحلیل هر ساعت:\n\n"
        + "\n\n".join(report)
        + "\n\n📰 اخبار مهم:\n"
        + news
        + "\n\n💡 تحلیل تحلیل‌گران:\n"
        + ideas
    )
    await send_long_message(context.bot, CHAT_ID, full_report, "گزارش کلی")
    print("دور تحلیل تمام شد. منتظر دور بعدی...")

last_signals = {}

async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    global last_signals
    for symbol in SYMBOLS:
        try:
            df = fetch_data(symbol)
            signal, explanation = analyze(df)
            if symbol not in last_signals or last_signals[symbol] != signal:
                if signal in ["سیگنال ورود (Long)", "سیگنال خروج (Short)"]:
                    text = f"⏰ آلارم سیگنال جدید!\n{symbol} ({TIMEFRAME}): {signal}\n{explanation}"
                    await send_long_message(context.bot, CHAT_ID, text, symbol)
            last_signals[symbol] = signal
            await asyncio.sleep(1)
        except Exception as e:
            continue

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button))
    app.job_queue.run_repeating(hourly_report, interval=3600, first=1)
    app.job_queue.run_repeating(alert_job, interval=1800, first=5)
    print("ربات آماده است.")
    app.run_polling()

if __name__ == "__main__":
    main()
