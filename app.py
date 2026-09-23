import os
import requests
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, FlexMessage, FlexContainer, TextMessage, QuickReply, QuickReplyItem, MessageAction
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET')

if channel_access_token is None or channel_secret is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET environment variables.')
    SystemExit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

# 儲存每個使用者的設定 (折數與 Tick 範圍)
user_settings = {}

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
    return net_profit, roi

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

def create_tick_table_flex_message(quote, discount, tick_range):
    p = quote['current_price']
    diff_sign = "+" if quote['diff'] > 0 else ""
    diff_color = "#ff453a" if quote['diff'] > 0 else ("#30d158" if quote['diff'] < 0 else "#8e8e93")
    
    # 往上漲的 Tick
    cur = p
    up_items = []
    for i in range(1, tick_range + 1):
        cur = step_tick(cur, 1)
        net_p, roi = calculate_trade(p, cur, 1000, discount)
        up_items.append((f"+{i}檔", cur, net_p, roi))
    
    # 往下跌的 Tick
    cur = p
    down_items = []
    for i in range(1, tick_range + 1):
        cur = step_tick(cur, -1)
        net_p, roi = calculate_trade(p, cur, 1000, discount)
        down_items.append((f"-{i}檔", cur, net_p, roi))

    table_contents = []
    
    # 放漲的 (反轉讓最高價在最上面)
    for tag, price, net_p, roi in reversed(up_items):
        p_color = "#ff453a" if net_p > 0 else "#30d158"
        p_sign = "+" if net_p > 0 else ""
        table_contents.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": tag, "size": "xs", "color": "#8e8e93", "flex": 1},
                {"type": "text", "text": f"{price:.2f}", "size": "xs", "color": "#ffffff", "weight": "bold", "flex": 2, "align": "center"},
                {"type": "text", "text": f"{p_sign}{net_p:,} ({p_sign}{roi:.1f}%)", "size": "xs", "color": p_color, "weight": "bold", "flex": 3, "align": "end"}
            ],
            "margin": "sm"
        })
        
    # 當前價基準列
    table_contents.append({
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": "現價基準", "size": "xs", "color": "#0a84ff", "flex": 1, "weight": "bold"},
            {"type": "text", "text": f"{p:.2f}", "size": "xs", "color": "#0a84ff", "weight": "bold", "flex": 2, "align": "center"},
            {"type": "text", "text": "0 (0.0%)", "size": "xs", "color": "#8e8e93", "weight": "bold", "flex": 3, "align": "end"}
        ],
        "margin": "sm"
    })

    # 放跌的
    for tag, price, net_p, roi in down_items:
        p_color = "#ff453a" if net_p > 0 else "#30d158"
        p_sign = "+" if net_p > 0 else ""
        table_contents.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": tag, "size": "xs", "color": "#8e8e93", "flex": 1},
                {"type": "text", "text": f"{price:.2f}", "size": "xs", "color": "#ffffff", "weight": "bold", "flex": 2, "align": "center"},
                {"type": "text", "text": f"{p_sign}{net_p:,} ({p_sign}{roi:.1f}%)", "size": "xs", "color": p_color, "weight": "bold", "flex": 3, "align": "end"}
            ],
            "margin": "sm"
        })

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
                "text": f"折讓:{discount} | ±{tick_range}檔",
                "size": "xxs",
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
                "size": "xl",
                "weight": "bold",
                "color": "#ffffff",
                "flex": 0
              },
              {
                "type": "text",
                "text": f"  {diff_sign}{quote['diff']:.2f} ({diff_sign}{quote['diff_percent']:.2f}%)",
                "size": "xs",
                "color": diff_color,
                "weight": "bold",
                "flex": 0
              }
            ],
            "margin": "xs"
          },
          {
            "type": "separator",
            "margin": "md",
            "color": "#38383a"
          },
          {
            "type": "box",
            "layout": "vertical",
            "contents": table_contents,
            "margin": "md"
          }
        ],
        "backgroundColor": "#1c1c1e",
        "paddingAll": "14px"
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
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 1. 處理手續費折讓設定 (支援預設或自訂如 折數0.38 / 折數1.0)
        if user_text.startswith("折數"):
            try:
                val_str = user_text.replace("折數", "").strip()
                discount = float(val_str)
                if user_id not in user_settings: user_settings[user_id] = {'discount': 0.25, 'tick': 5}
                user_settings[user_id]['discount'] = discount
                reply_text = f"✅ 手續費折讓已更新為：【{discount}】"
            except:
                reply_text = "格式錯誤，請輸入如「折數0.25」或「折數1.0」"
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))
            return

        # 2. 處理 Tick 範圍設定 (如 tick5, tick10, tick15)
        if user_text.startswith("tick"):
            try:
                t_val = int(user_text.replace("tick", "").strip())
                if user_id not in user_settings: user_settings[user_id] = {'discount': 0.25, 'tick': 5}
                user_settings[user_id]['tick'] = t_val
                reply_text = f"✅ 檔位範圍已更新為：【±{t_val} 個 Tick】"
            except:
                reply_text = "格式錯誤，請輸入如「tick5」或「tick10」"
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))
            return

        # 3. 對應圖文選單 A 區塊：「手續費設定」
        if user_text == "手續費設定":
            settings = user_settings.get(user_id, {'discount': 0.25, 'tick': 5})
            reply_text = f"⚙️ 目前手續費折讓設定：【{settings['discount']}】\n\n請點擊下方按鈕快速切換，或直接傳送訊息（例如「折數0.38」、「折數1.0」）。"
            quick_reply = QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="0.2折", text="折數0.2")),
                QuickReplyItem(action=MessageAction(label="0.25折", text="折數0.25")),
                QuickReplyItem(action=MessageAction(label="0.3折", text="折數0.3")),
                QuickReplyItem(action=MessageAction(label="0.5折", text="折數0.5")),
                QuickReplyItem(action=MessageAction(label="1.0折(無折)", text="折數1.0")),
            ])
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text, quick_reply=quick_reply)]))
            return

        # 4. 對應圖文選單 B 區塊：「顯示Tick」
        if user_text == "顯示Tick":
            settings = user_settings.get(user_id, {'discount': 0.25, 'tick': 5})
            reply_text = f"⚙️ 目前檔位範圍設定：【±{settings['tick']} 個 Tick】\n\n請點擊下方按鈕選擇要顯示幾個檔位："
            quick_reply = QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="±5 檔", text="tick5")),
                QuickReplyItem(action=MessageAction(label="±10 檔", text="tick10")),
                QuickReplyItem(action=MessageAction(label="±15 檔", text="tick15")),
                QuickReplyItem(action=MessageAction(label="±20 檔", text="tick20")),
            ])
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text, quick_reply=quick_reply)]))
            return

        # 5. 查詢 4 位數股票代號
        if user_text.isdigit() and len(user_text) == 4:
            quote = get_stock_quote(user_text)
            if quote:
                settings = user_settings.get(user_id, {'discount': 0.25, 'tick': 5})
                flex_msg = create_tick_table_flex_message(quote, settings['discount'], settings['tick'])
                
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=f"{quote['name']} 檔位損益表", contents=flex_msg)]
                    )
                )
                return
            else:
                reply_text = f"找不到代號 【{user_text}】 的資料。"
        else:
            reply_text = "請輸入 4 位數股票代號（例如 2330），或點擊左下角選單調整設定！"

        line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))

if __name__ == '__main__':
    app.run(port=5000)
