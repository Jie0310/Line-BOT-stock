import os
import requests
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, FlexMessage, FlexContainer, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET')

if channel_access_token is None or channel_secret is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET environment variables.')
    SystemExit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.10
    if price < 500: return 0.50
    if price < 1000: return 1.00
    return 5.00

def step_tick(price, direction):
    p = float(price)
    tick = get_tick_size(p)
    if direction > 0:
        return round(p + tick, 2)
    else:
        return max(0.01, round(p - tick, 2))

def calculate_trade(base_p, target_p, shares, discount=0.25, tax_rate=0.0015):
    buy_amt = base_p * shares
    sell_amt = target_p * shares
    min_fee = 20
    buy_fee = max(min_fee, int(buy_amt * 0.001425 * discount))
    sell_fee = max(min_fee, int(sell_amt * 0.001425 * discount))
    tax = int(sell_amt * tax_rate)
    total_cost = buy_fee + sell_fee + tax
    net_profit = int(sell_amt - buy_amt - total_cost)
    capital_base = buy_amt + buy_fee
    roi = (net_profit / capital_base * 100) if capital_base > 0 else 0
    return net_profit, roi, total_cost

def get_stock_quote(symbol):
    sym = symbol.strip().upper()
    worker_url = f"https://twse-proxy.yijhuang8931.workers.dev?sym={sym}"
    try:
        res = requests.get(worker_url, timeout=4)
        if res.status_code != 200:
            return None
        data = res.json()
        meta = None
        if data.get('quoteResponse') and data['quoteResponse'].get('result'):
            meta = data['quoteResponse']['result'][0]
        elif data.get('chart') and data['chart'].get('result'):
            meta = data['chart'].get('result')[0].get('meta', {})
            
        if not meta:
            return None
            
        name = meta.get('shortName') or meta.get('symbol') or sym
        current_price = meta.get('regularMarketClose') or meta.get('regularMarketPrice') or meta.get('previousClose', 0)
        prev_close = meta.get('regularMarketPreviousClose') or meta.get('previousClose', current_price)
        diff = current_price - prev_close
        diff_percent = (diff / prev_close * 100) if prev_close > 0 else 0
        
        return {
            'symbol': sym,
            'name': name,
            'current_price': current_price,
            'prev_close': prev_close,
            'diff': diff,
            'diff_percent': diff_percent
        }
    except Exception as e:
        print(f"Error fetching quote: {e}")
        return None

def create_stock_flex_message(quote):
    p = quote['current_price']
    diff_sign = "+" if quote['diff'] > 0 else ""
    diff_color = "#ff453a" if quote['diff'] > 0 else ("#30d158" if quote['diff'] < 0 else "#8e8e93")
    
    # 計算漲停價 (+10%) 與跌停價 (-10%)
    up_limit = round(quote['prev_close'] * 1.10, 2)
    down_limit = round(quote['prev_close'] * 0.90, 2)
    up_profit, up_roi, _ = calculate_trade(p, up_limit, 1000)
    down_loss, down_roi, _ = calculate_trade(p, down_limit, 1000)

    flex_content = {
      "type": "bubble",
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {
            "type": "text",
            "text": f"{quote['name']} ({quote['symbol']})",
            "weight": "bold",
            "size": "lg",
            "color": "#ffffff"
          },
          {
            "type": "box",
            "layout": "baseline",
            "contents": [
              {
                "type": "text",
                "text": f"{p:.2f}",
                "size": "xxl",
                "weight": "bold",
                "color": "#ffffff",
                "flex": 0
              },
              {
                "type": "text",
                "text": f"  {diff_sign}{quote['diff']:.2f} ({diff_sign}{quote['diff_percent']:.2f}%)",
                "size": "sm",
                "color": diff_color,
                "weight": "bold",
                "flex": 0
              }
            ],
            "margin": "md"
          },
          {
            "type": "separator",
            "margin": "lg",
            "color": "#38383a"
          },
          {
            "type": "box",
            "layout": "vertical",
            "contents": [
              {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                  {"type": "text", "text": "當前跳動單位", "size": "sm", "color": "#8e8e93", "flex": 1},
                  {"type": "text", "text": f"{get_tick_size(p)} 元", "size": "sm", "color": "#ffffff", "align": "end", "weight": "bold"}
                ],
                "margin": "sm"
              },
              {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                  {"type": "text", "text": "整張買進總額(含費)", "size": "sm", "color": "#8e8e93", "flex": 1},
                  {"type": "text", "text": f"{int(p * 1000):,} 元", "size": "sm", "color": "#ffffff", "align": "end", "weight": "bold"}
                ],
                "margin": "sm"
              },
              {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                  {"type": "text", "text": "漲停賺多少 (+10%)", "size": "sm", "color": "#8e8e93", "flex": 1},
                  {"type": "text", "text": f"+{up_profit:,} 元 ({up_roi:.2f}%)", "size": "sm", "color": "#ff453a", "align": "end", "weight": "bold"}
                ],
                "margin": "sm"
              },
              {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                  {"type": "text", "text": "跌停賠多少 (-10%)", "size": "sm", "color": "#8e8e93", "flex": 1},
                  {"type": "text", "text": f"{down_loss:,} 元 ({down_roi:.2f}%)", "size": "sm", "color": "#30d158", "align": "end", "weight": "bold"}
                ],
                "margin": "sm"
              }
            ],
            "margin": "lg"
          }
        ],
        "backgroundColor": "#1c1c1e",
        "paddingAll": "20px"
      }
    }
    return FlexContainer.from_dict(flex_content)

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        user_text = event.message.text.strip()

        if user_text.isdigit() and len(user_text) == 4:
            quote = get_stock_quote(user_text)
            if quote:
                flex_msg = create_stock_flex_message(quote)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=f"{quote['name']} 即時行情與試算", contents=flex_msg)]
                    )
                )
                return
            else:
                reply_text = f"找不到代號 【{user_text}】 的資料。"
        else:
            reply_text = "請輸入 4 位數股票代號（例如 2330），直接為您計算即時損益與行情！"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
