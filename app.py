import os
import requests
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, FlexMessage, FlexContainer, TextMessage, QuickReply, QuickReplyItem, PostbackAction, MessageAction
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

app = Flask(__name__)

channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET')

if channel_access_token is None or channel_secret is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET environment variables.')
    SystemExit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

# 記錄每個使用者的手續費折讓設定（簡單記憶體儲存，重啟會重置，後續可改接資料庫）
user_discounts = {}

def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.10
    if price < 500: return 0.50
    if price < 1000: return 1.00
    return 5.00

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

def create_stock_flex_message(quote, discount):
    p = quote['current_price']
    diff_sign = "+" if quote['diff'] > 0 else ""
    diff_color = "#ff453a" if quote['diff'] > 0 else ("#30d158" if quote['diff'] < 0 else "#8e8e93")
    
    up_limit = round(quote['prev_close'] * 1.10, 2)
    down_limit = round(quote['prev_close'] * 0.90, 2)
    up_profit, up_roi, _ = calculate_trade(p, up_limit, 1000, discount)
    down_loss, down_roi, _ = calculate_trade(p, down_limit, 1000, discount)

    flex_content = {
      "type": "bubble",
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {
            "type": "box",
            "layout": "horizontal",
            "contents": [
              {
                "type": "text",
                "text": f"{quote['name']} ({quote['symbol']})",
                "weight": "bold",
                "size": "md",
                "color": "#ffffff",
                "flex": 1
              },
              {
                "type": "text",
                "text": f"折讓: {discount*10:.1f}折",
                "size": "xs",
                "color": "#0a84ff",
                "align": "end",
                "weight": "bold",
                "flex": 0
              }
            ]
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
            "margin": "sm"
          },
          {
            "type": "separator",
            "margin": "md",
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
            "margin": "md"
          }
        ],
        "backgroundColor": "#1c1c1e",
        "paddingAll": "16px"
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
    user_id = event.source.user_id if event.source else 'default'
    user_text = event.message.text.strip()
    
    # 檢查是否為設定指令
    if user_text.startswith("折數"):
        try:
            val = float(user_text.replace("折數", "").strip())
            discount = val / 10.0
            user_discounts[user_id] = discount
            reply_text = f"✅ 已成功將您的手續費設定為 【{val} 折】！\n請直接輸入 4 位數股票代號（例如 2330）開始計算。"
        except:
            reply_text = "設定格式錯誤，請輸入「折數2.5」或「折數3」。"
            
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if user_text.isdigit() and len(user_text) == 4:
            quote = get_stock_quote(user_text)
            if quote:
                discount = user_discounts.get(user_id, 0.25) # 預設 2.5 折
                flex_msg = create_stock_flex_message(quote, discount)
                
                # 加入快捷按鈕讓使用者隨時切換折數
                quick_reply = QuickReply(items=[
                    QuickReplyItem(action=MessageAction(label="設定 2折", text="折數2")),
                    QuickReplyItem(action=MessageAction(label="設定 2.5折", text="折數2.5")),
                    QuickReplyItem(action=MessageAction(label="設定 3折", text="折數3")),
                    QuickReplyItem(action=MessageAction(label="設定 2.8折", text="折數2.8")),
                ])
                
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=f"{quote['name']} 即時行情", contents=flex_msg, quick_reply=quick_reply)]
                    )
                )
                return
            else:
                reply_text = f"找不到代號 【{user_text}】 的資料。"
        else:
            reply_text = "請輸入 4 位數股票代號（例如 2330），或點擊下方快捷按鈕隨時調整手續費折讓！"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
