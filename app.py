import threading
import time
import shutil
import datetime

# for SSL
import os
import certifi
# for record data
import json
# for interconnect
from flask import Flask, request, abort

from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    StickerMessage,
    Emoji,
    ImageMessage,
    TemplateMessage,
    ConfirmTemplate,
    ButtonsTemplate,
    CarouselTemplate,
    CarouselColumn,
    ImageCarouselTemplate,
    ImageCarouselColumn,
    MessageAction,
    URIAction,
    PostbackAction,
    DatetimePickerAction,
    FlexMessage, 
    FlexContainer
)
from linebot.v3.webhooks import (
    MessageEvent,
    FollowEvent,
    PostbackEvent,
    TextMessageContent
)
from linebot.v3.messaging import (
    ReplyMessageRequest,
    PushMessageRequest,
    BroadcastRequest,
    MulticastRequest
)



# LINE Bot 設定
# charry



configuration = Configuration(access_token=os.getenv('CHANNEL_ACCESS_TOKEN')) # CHANNEL_ACCESS_TOKEN
line_handler = WebhookHandler(os.getenv('CHANNEL_SECRET')) # CHANNEL_SECRET



# 用戶資料檔案路徑
USER_DATA_FILE = 'user_data.json'
# 公告檔案路徑
ANNOUNCEMENT_FILE = 'announcement.json'
HISTORY_FOLDER = './announcement_history'

# 確保歷史資料夾存在
if not os.path.exists(HISTORY_FOLDER):
    os.makedirs(HISTORY_FOLDER)

# 解決 SSL 證書驗證問題
# os.environ['SSL_CERT_FILE'] = certifi.where()

app = Flask(__name__)


# 用戶狀態追蹤
user_states = {}
# 訊息轉發狀態追蹤
message_forwarding = {}

# 初始化或讀取用戶資料
def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:  # 檢查文件是否為空
                    return json.loads(content)
                else:
                    app.logger.warning("User data file exists but is empty. Returning empty dict.")
                    return {}
        except json.JSONDecodeError as e:
            app.logger.error(f"JSON decode error: {str(e)}. Creating new user data file.")
            # 如果檔案存在但格式不正確，建立一個新的空字典
            with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            return {}
    else:
        # 如果檔案不存在，建立一個新的空字典
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        return {}

# 儲存用戶資料
def save_user_data(user_data):
    with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)

# 檢查用戶是否已註冊
def is_user_registered(user_id):
    user_data = load_user_data()
    return user_id in user_data

# 獲取所有已註冊用戶的名稱列表
def get_all_user_names():
    user_data = load_user_data()
    return [(user_id, info['name']) for user_id, info in user_data.items()]

# 根據名稱查找用戶ID
def find_user_id_by_name(name):
    user_data = load_user_data()
    for user_id, info in user_data.items():
        if info['name'].lower() == name.lower():
            return user_id
    return None

# 檢查名稱是否已存在
def is_name_exists(name):
    user_data = load_user_data()
    for info in user_data.values():
        if info['name'].lower() == name.lower():
            return True
    return False

# 創建註冊提示
def create_register_prompt():
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "您尚未註冊！",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "請點擊下方按鈕進行註冊，以便使用所有功能。",
                    "margin": "md",
                    "align": "center",
                    "wrap": True
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#8B5A2B",  
                    "action": {
                        "type": "postback",
                        "label": "註冊！",
                        "data": "register",
                        "displayText": "我要註冊"
                    },
                    "margin": "md"
                }
            ]
        }
    }
    
    return FlexMessage(alt_text="註冊提示", contents=FlexContainer.from_dict(flex_content))

# 處理公告訊息
def process_announcements():
    # 檢查是否存在公告檔案
    if os.path.exists(ANNOUNCEMENT_FILE):
        try:
            # 讀取公告檔案
            with open(ANNOUNCEMENT_FILE, 'r', encoding='utf-8') as f:
                announcement = json.load(f)
            
            app.logger.info(f"找到公告檔案，開始處理: {announcement['message_id']}")
            
            # 檢查是否所有接收者都已處理完成
            all_processed = True
            for recipient in announcement['recipients']:
                if recipient['status'] == 'pending':
                    all_processed = False
                    break
            
            # 如果所有接收者都已處理，直接移動檔案到歷史資料夾
            if all_processed:
                timestamp = datetime.datetime.fromtimestamp(announcement['sent_at']/1000).strftime('%Y%m%d_%H%M%S')
                history_file = os.path.join(HISTORY_FOLDER, f"announcement_{timestamp}.json")
                
                # 複製到歷史資料夾
                shutil.copy2(ANNOUNCEMENT_FILE, history_file)
                
                # 刪除原始檔案
                os.remove(ANNOUNCEMENT_FILE)
                
                app.logger.info(f"所有接收者已處理，公告檔案已移至歷史資料夾: {history_file}")
                return
            
            # 使用 LINE API 發送訊息
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                
                # 遍歷所有接收者
                for recipient in announcement['recipients']:
                    if recipient['status'] == 'pending':
                        try:
                            # 發送訊息
                            line_bot_api.push_message(
                                PushMessageRequest(
                                    to=recipient['user_id'],
                                    messages=[
                                        TextMessage(text=f"📢 系統公告：\n{announcement['content']}")
                                        # StickerMessage(package_id="11537", sticker_id="52002736")  # 收到訊息貼圖
                                    ]
                                )
                            )
                            
                            # 更新狀態為已發送
                            recipient['status'] = 'sent'
                            app.logger.info(f"成功發送公告給 {recipient['name']} ({recipient['user_id']})")
                        except Exception as e:
                            app.logger.error(f"發送公告給 {recipient['name']} 失敗: {str(e)}")
                
                # 保存更新後的公告（包含已更新的狀態）
                with open(ANNOUNCEMENT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(announcement, f, ensure_ascii=False, indent=4)
                
                # 檢查是否所有接收者都已處理完成
                all_processed = True
                for recipient in announcement['recipients']:
                    if recipient['status'] == 'pending':
                        all_processed = False
                        break
                
                # 如果所有接收者都已處理，移動檔案到歷史資料夾
                if all_processed:
                    timestamp = datetime.datetime.fromtimestamp(announcement['sent_at']/1000).strftime('%Y%m%d_%H%M%S')
                    history_file = os.path.join(HISTORY_FOLDER, f"announcement_{timestamp}.json")
                    
                    # 複製到歷史資料夾
                    shutil.copy2(ANNOUNCEMENT_FILE, history_file)
                    
                    # 刪除原始檔案
                    os.remove(ANNOUNCEMENT_FILE)
                    
                    app.logger.info(f"公告處理完成，已移至歷史資料夾: {history_file}")
                
        except Exception as e:
            app.logger.error(f"處理公告檔案時發生錯誤: {str(e)}")

# 背景任務：檢查公告檔案
def announcement_checker():
    while True:
        try:
            # 檢查並處理公告
            process_announcements()
            # 每5秒檢查一次
            time.sleep(5)
        except Exception as e:
            app.logger.error(f"公告檢查任務發生錯誤: {str(e)}")
            time.sleep(10)  # 發生錯誤時，等待稍長時間再重試

# 創建功能選單
def create_function_menu(user_name):
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"{user_name}        (╭￣3￣)╭♡",
                    "weight": "bold",
                    "size": "xl"
                },
                {
                    "type": "text",
                    "text": "請選擇以下功能：",
                    "margin": "md"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#5E3A1C",  # 深咖啡色
                    "action": {
                        "type": "message",
                        "label": "發送訊息",
                        "text": "send"
                    },
                    "margin": "md"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#8B5A2B",  # 中咖啡色
                    "action": {
                        "type": "uri",
                        "label": "官網介紹",
                        "uri": "https://www.instagram.com/cherry_ho1014/"
                    },
                    "margin": "md"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#BC8F5F",  # 淺咖啡色
                    "action": {
                        "type": "message",
                        "label": "重新命名",
                        "text": "register"
                    },
                    "margin": "md"
                }
            ]
        }
    }
    
    return FlexMessage(alt_text="功能選單", contents=FlexContainer.from_dict(flex_content))



    

@app.route("/callback", methods=['POST'])
def callback():
    # 取得 X-Line-Signature 頭部值
    signature = request.headers['X-Line-Signature']

    # 取得請求內容
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 處理 webhook 主體
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# 處理加入事件
@line_handler.add(FollowEvent)
def handle_follow(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        user_id = event.source.user_id
        
        # 載入現有用戶資料
        user_data = load_user_data()
        
        # 檢查用戶是否已經註冊
        if user_id in user_data:
            welcome_message = f"歡迎回來，{user_data[user_id]['name']}！"
            
            # 回覆歡迎訊息和貼圖，並顯示功能選單
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=welcome_message),
                        StickerMessage(package_id="11537", sticker_id="52002734")  # 歡迎回來貼圖
                    ]
                )
            )
        else:
            # 設定用戶狀態為等待註冊
            user_states[user_id] = "waiting_for_name"
            welcome_message = "歡迎加入！請輸入您的名字進行註冊："
            
            # 回覆歡迎訊息和貼圖
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text=welcome_message),
                            StickerMessage(package_id="11537", sticker_id="52002739")  # 歡迎加入貼圖
                        ]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")

# 處理文字訊息
@line_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        user_id = event.source.user_id
        text = event.message.text
        
        # 檢查用戶是否在註冊流程中
        if user_id in user_states and user_states[user_id] == "waiting_for_name":
            # 檢查名稱是否已存在
            if is_name_exists(text):
                # 名稱已存在，請用戶重新輸入
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="抱歉，此名稱已被使用\n請輸入一個不同的名稱："),
                                StickerMessage(package_id="11537", sticker_id="52002753")  # 抱歉貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return
            
            # 載入現有用戶資料
            user_data = load_user_data()
            
            # 儲存用戶名稱
            user_data[user_id] = {
                "name": text,
                "registered_at": event.timestamp  # 可選：記錄註冊時間
            }
            
            # 儲存更新後的用戶資料
            save_user_data(user_data)
            
            # 清除用戶狀態
            del user_states[user_id]
            
            # 回覆確認訊息和貼圖，並顯示功能選單
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text=f"{text}！您已成功註冊。"),
                            StickerMessage(package_id="446", sticker_id="1989")  # 註冊成功貼圖
                            
                        ]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")
                
        # 處理訊息轉發流程
        elif user_id in message_forwarding:
            # 先檢查是否為取消命令
            if text.lower() == "cancel" or text == "取消操作":
                del message_forwarding[user_id]
                try:
                    # 載入用戶資料以獲取名稱
                    user_data = load_user_data()
                    user_name = user_data[user_id]['name']
                    
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="已取消訊息發送操作。"),
                                StickerMessage(package_id="446", sticker_id="2027")  # 取消操作貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return  # 重要：處理完取消命令後立即返回
    
            # 檢查當前階段
            if message_forwarding[user_id]['stage'] == 'waiting_for_recipient':
                # 用戶正在選擇接收者
                try:
                    # 嘗試將輸入解析為數字
                    recipient_index = int(text.strip()) - 1
                    recipient_list = message_forwarding[user_id]['recipient_list']
                    
                    # 檢查索引是否有效
                    if 0 <= recipient_index < len(recipient_list):
                        recipient_id, recipient_name = recipient_list[recipient_index]
                        
                        # 更新狀態
                        message_forwarding[user_id]['recipient_id'] = recipient_id
                        message_forwarding[user_id]['recipient_name'] = recipient_name
                        message_forwarding[user_id]['stage'] = 'waiting_for_message'
                        
                        # 詢問用戶要發送的訊息
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=f"請輸入您要發送給 {recipient_name} 的訊息：")]
                            )
                        )
                    else:
                        # 索引超出範圍
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[
                                    TextMessage(text=f"無效的選擇。請輸入1到{len(recipient_list)}之間的數字，或輸入 'cancel' 取消操作。"),
                                    StickerMessage(package_id="11537", sticker_id="52002744")  
                                ]
                            )
                        )
                except ValueError:
                    # 輸入不是數字
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text=f"請輸入有效的數字編號，或輸入 'cancel' (取消)"),
                                StickerMessage(package_id="11537", sticker_id="52002744")  # 無效輸入貼圖
                            ]
                        )
                    )
            
            elif message_forwarding[user_id]['stage'] == 'waiting_for_message':
                # 用戶正在輸入訊息內容
                message_content = text
                recipient_id = message_forwarding[user_id]['recipient_id']
                recipient_name = message_forwarding[user_id]['recipient_name']
                
                # 載入用戶資料以獲取發送者名稱
                user_data = load_user_data()
                sender_name = user_data[user_id]['name']
                
                # 發送訊息給接收者
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=recipient_id,
                            messages=[
                                TextMessage(text=f"來自 {sender_name} 的訊息：\n\n{message_content}"),
                                StickerMessage(package_id="11537", sticker_id="52002736")  # 收到訊息貼圖
                            ]
                        )
                    )
                    
                    # 通知發送者訊息已發送，並顯示功能選單
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text=f"成功發送給 {recipient_name}   (*´з｀*) "),
                                # StickerMessage(package_id="446", sticker_id="2010"),  # 成功發送貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"發送訊息錯誤: {str(e)}")
                    # 通知發送者訊息發送失敗
                    try:
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[
                                    TextMessage(text=f"發送訊息失敗：{str(e)}"),
                                    StickerMessage(package_id="11537", sticker_id="52002752")  # 失敗貼圖
                                ]
                            )
                        )
                    except Exception as inner_e:
                        app.logger.error(f"回覆錯誤訊息時發生錯誤: {str(inner_e)}")
                
                # 清除訊息轉發狀態
                del message_forwarding[user_id]
                
        # 處理 "cancel" 命令 - 取消當前操作
        elif text.lower() == "cancel" or text == "取消操作":
            if user_id in message_forwarding:
                del message_forwarding[user_id]
                try:
                    # 載入用戶資料以獲取名稱
                    user_data = load_user_data()
                    user_name = user_data[user_id]['name']
                    
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="已取消訊息發送操作。"),
                                StickerMessage(package_id="446", sticker_id="2018")  # 取消操作貼圖
                                
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
            elif user_id in user_states:
                del user_states[user_id]
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="已取消當前操作。"),
                                StickerMessage(package_id="11537", sticker_id="52002741")  # 取消操作貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
            else:
                try:
                    # 載入用戶資料以獲取名稱
                    user_data = load_user_data()
                    if user_id in user_data:
                        user_name = user_data[user_id]['name']
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[
                                    TextMessage(text="目前沒有進行中的操作可以取消。"),
                                    StickerMessage(package_id="446", sticker_id="2010")
                                ]
                            )
                        )
                    else:
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[
                                    create_register_prompt()
                                ]
                            )
                        )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")    

        
        # 處理 "register" 命令
        elif text.lower() == "register":
            # 設定用戶狀態為等待註冊
            user_states[user_id] = "waiting_for_name"
            
            # 回覆註冊提示
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text="請輸入您的名字進行註冊或重新註冊："),
                            StickerMessage(package_id="446", sticker_id="1998")  # 註冊提示貼圖
                        ]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")
        # 處理 "intro" 命令 - 重定向到官網
        elif text.lower() == "intro":
            # 檢查用戶是否已註冊
            if is_user_registered(user_id):
                user_data = load_user_data()
                user_name = user_data[user_id]['name']
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="請點擊以下按鈕訪問官網："),
                                TemplateMessage(
                                    alt_text="官網連結",
                                    template=ButtonsTemplate(
                                        title="官網介紹",
                                        text="點擊下方按鈕訪問官網",
                                        actions=[
                                            URIAction(
                                                label="前往官網",
                                                uri="https://www.instagram.com/cherry_ho1014/"
                                            )
                                        ]
                                    )
                                )
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
            else:
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_register_prompt()
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")


        # 處理 "send" 命令 - 開始訊息轉發流程
        elif text.lower() == "send" or text =="發送訊息":
            # 檢查用戶是否已註冊
            if not is_user_registered(user_id):
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_register_prompt()
                                
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return
            
            # 獲取所有用戶名稱列表
            users = get_all_user_names()
            if len(users) <= 1:  # 只有當前用戶
                try:
                    # 載入用戶資料以獲取名稱
                    user_data = load_user_data()
                    user_name = user_data[user_id]['name']
                    
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="目前沒有其他註冊用戶可以發送訊息。"),
                                StickerMessage(package_id="11537", sticker_id="52002748")  # 沒有用戶貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return
            
            # 準備用戶列表，排除當前用戶
            recipient_list = []
            for uid, name in users:
                if uid != user_id:  # 排除自己
                    recipient_list.append((uid, name))
            
            # 創建一個 Flex Message 用於顯示可選的收件人
            recipient_buttons = []
            for i, (uid, name) in enumerate(recipient_list):
                # 為每個收件人創建一個按鈕
                recipient_buttons.append({
                    "type": "button",
                    "style": "primary",
                    "color": "#D8BC8B",  # 棕色
                    "action": {
                        "type": "postback",
                        "label": name,
                        "data": f"recipient_{i}",  # 使用索引作為 postback 數據
                        "displayText": f"我要發送訊息給 {name}"  # 當用戶點擊時顯示的文字
                    },
                    "margin": "md"
                })
            
            # 創建 Flex Message
            flex_content = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "選擇收件人",
                            "weight": "bold",
                            "size": "xxl",
                            "align": "center"
                        },
                        {
                            "type": "text",
                            "text": "請點選您要發送訊息的對象：",
                            "margin": "md",
                            "align": "center"
                        }
                    ] + recipient_buttons + [
                        {
                            "type": "button",
                            "style": "secondary",
                            #"color":"#F9E6D2",
                            "action": {
                                "type": "message",
                                "label": "取消",
                                "text": "cancel"
                            },
                            "margin": "md"
                        }
                    ]
                }
            }
            
            # 初始化訊息轉發狀態
            message_forwarding[user_id] = {
                'stage': 'waiting_for_recipient',
                'recipient_id': None,
                'recipient_name': None,
                'recipient_list': recipient_list  # 儲存接收者列表，以便後續通過索引查找
            }
            
            # 回覆 Flex Message
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="選擇收件人", contents=FlexContainer.from_dict(flex_content))]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")
                # 如果 Flex Message 失敗，回退到文字模式
                try:
                    user_list_text = "\n".join([f" ({i+1}). {name}" for i, (_, name) in enumerate(recipient_list)])
                    emojis = [
                        Emoji(index=9, product_id="670e0cce840a8236ddd4ee4c", emoji_id="152"),
                        Emoji(index=11, product_id="670e0cce840a8236ddd4ee4c", emoji_id="151")
                    ]
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"你想發送訊息給  $ $\n======================\n{user_list_text}\n======================\n 請直接輸入數字(無需括號)  ‼️ ", emojis=emojis)]
                        )
                    )
                except Exception as inner_e:
                    app.logger.error(f"回復備用訊息錯誤: {str(inner_e)}")

        
        
                
        # 處理 "func_list" 命令 - 顯示功能選單
        elif text=="功能列表"or text.lower() == "func_list":
            # 檢查用戶是否已註冊
            if is_user_registered(user_id):
                user_data = load_user_data()
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_function_menu(user_data[user_id]['name'])
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
            else:
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_register_prompt()
                                
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                
        else:
            # 檢查用戶是否已註冊
            try:
                if not is_user_registered(user_id):
                    # 用戶未註冊，發送 Flex 訊息提示註冊
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_register_prompt()
                            ]
                        )
                    )
                else:
                    # 用戶已註冊，但不顯示功能選單，只回覆訊息
                    user_data = load_user_data()
                    user_name = user_data[user_id]['name']
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text=f"你好，{user_name}！你說了：{text}")
                                # 移除了功能選單
                            ]
                        )
                    )

            except Exception as e:
                app.logger.error(f"處理訊息錯誤: {str(e)}")
                # 發生錯誤時，回覆一個通用訊息
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="抱歉，處理您的訊息時發生錯誤。請稍後再試。"),
                                StickerMessage(package_id="11537", sticker_id="52002752")  # 錯誤貼圖
                            ]
                        )
                    )
                except Exception as inner_e:
                    app.logger.error(f"回覆錯誤訊息時發生錯誤: {str(inner_e)}")

# 處理 Postback 事件
@line_handler.add(PostbackEvent)
def handle_postback(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        user_id = event.source.user_id
        data = event.postback.data
        
        # 處理收件人選擇
        if data.startswith("recipient_"):
            # 檢查用戶是否在訊息轉發流程中
            if user_id in message_forwarding and message_forwarding[user_id]['stage'] == 'waiting_for_recipient':
                try:
                    # 從 postback 數據中獲取收件人索引
                    recipient_index = int(data.split("_")[1])
                    recipient_list = message_forwarding[user_id]['recipient_list']
                    
                    # 檢查索引是否有效
                    if 0 <= recipient_index < len(recipient_list):
                        recipient_id, recipient_name = recipient_list[recipient_index]
                        
                        # 更新狀態
                        message_forwarding[user_id]['recipient_id'] = recipient_id
                        message_forwarding[user_id]['recipient_name'] = recipient_name
                        message_forwarding[user_id]['stage'] = 'waiting_for_message'
                        
                        # 詢問用戶要發送的訊息
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=f"請輸入您要發送給 {recipient_name} 的訊息：")]
                            )
                        )
                    else:
                        # 索引超出範圍
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[
                                    TextMessage(text="無效的選擇。請重新選擇收件人，或輸入 'cancel' 取消操作。"),
                                    StickerMessage(package_id="11537", sticker_id="52002744")  
                                ]
                            )
                        )
                except (ValueError, IndexError) as e:
                    # 處理錯誤
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text=f"處理您的選擇時發生錯誤：{str(e)}。請重新嘗試或輸入 'cancel' 取消操作。"),
                                StickerMessage(package_id="11537", sticker_id="52002744")
                            ]
                        )
                    )
            else:
                # 用戶不在訊息轉發流程中
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="請先輸入 'send' 來開始發送訊息。")]
                    )
                )

        elif data == "register":
            # 設定用戶狀態為等待註冊
            user_states[user_id] = "waiting_for_name"
            
            # 回覆註冊提示
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text="請輸入您的名字進行註冊或重新註冊："),
                            StickerMessage(package_id="11537", sticker_id="52002749")  # 註冊提示貼圖
                        ]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")
        
        elif data == "send":
            # 檢查用戶是否已註冊
            if not is_user_registered(user_id):
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_register_prompt()
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return
            
            # 獲取所有用戶名稱列表
            users = get_all_user_names()
            if len(users) <= 1:  # 只有當前用戶
                try:
                    # 載入用戶資料以獲取名稱
                    user_data = load_user_data()
                    user_name = user_data[user_id]['name']
                    
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="目前沒有其他註冊用戶可以發送訊息。"),
                                StickerMessage(package_id="11537", sticker_id="52002748")  # 沒有用戶貼圖
                            ]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"回覆訊息錯誤: {str(e)}")
                return
            
            # 準備用戶列表訊息，排除當前用戶
            recipient_list = []
            for uid, name in users:
                if uid != user_id:  # 排除自己
                    recipient_list.append((uid, name))
            
            user_list_text = "\n".join([f"   {i+1}. {name}" for i, (_, name) in enumerate(recipient_list)])
            
            # 初始化訊息轉發狀態
            message_forwarding[user_id] = {
                'stage': 'waiting_for_recipient',
                'recipient_id': None,
                'recipient_name': None,
                                'recipient_list': recipient_list  # 儲存接收者列表，以便後續通過索引查找
            }
            
            # 回覆用戶列表
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"請輸入您要發送訊息的用戶編號：\n\n{user_list_text}\n\n(請直接輸入數字編號)")]
                    )
                )
            except Exception as e:
                app.logger.error(f"回覆訊息錯誤: {str(e)}")

# 主程式入口
if __name__ == "__main__":
    # 確保用戶資料檔案存在且格式正確
    load_user_data()
        # 啟動背景任務
    announcement_thread = threading.Thread(target=announcement_checker)
    announcement_thread.daemon = True  # 設為守護線程，主程序結束時自動終止
    announcement_thread.start()
   
    app.run(debug=True, port=5001)

