import re
import os
from datetime import datetime, timezone, timedelta
import requests
import json

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')

def ensure_folder_exists(folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

# 버전 1.20 (기존 수집기의 기능들 추가 - 수집 메시지 유형(구독선물, 미션후원, 미션참여, 영상후원, 파티후원), 기존 메시지 유형 보완, 시청자 정보 및 목록, NoneType 오류 대응, 채팅 기록 최적화 및 개선, 채팅 채널ID 표시, 각종 버그 수정)
def fetch_and_save_chat_data(vodId):
    ensure_folder_exists(LOG_PATH)

    nextPlayerMessageTime = "0"
    temp_file_path = os.path.join(LOG_PATH, f"chatLog-{vodId}_temp.log")
    
    # 사용자 해시값 추적을 위한 딕셔너리
    user_hashes = {}
    # 사용자 상세 정보를 위한 딕셔너리 추가
    user_details = {}
    
    chat_data_collected = False  # 채팅 데이터가 수집되었는지 확인하는 플래그
    streamer_nickname = None  # 스트리머 닉네임을 저장할 변수
    chat_channel_id = None  # 채팅 채널 ID를 저장할 변수

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/'
        }

        # 임시 파일에 먼저 저장
        with open(temp_file_path, 'w', encoding='utf-8') as file:
            while True:
                url = f"https://api.chzzk.naver.com/service/v1/videos/{vodId}/chats?playerMessageTime={nextPlayerMessageTime}"
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()

                if data['code'] == 200 and data['content']['videoChats']:
                    video_chats = data['content']['videoChats']
                    chat_data_collected = True  # 채팅 데이터가 있음을 표시
                    
                    for chat in video_chats:
                        try:
                            # chat 객체가 None이거나 필수 필드가 없는 경우 건너뛰기
                            if chat is None or not isinstance(chat, dict):
                                continue
                                
                            # 필수 필드 확인
                            if 'messageTime' not in chat or 'userIdHash' not in chat:
                                continue
                            
                            # 채팅 채널 ID 저장 (첫 번째로 발견된 것 사용)
                            if chat_channel_id is None and 'chatChannelId' in chat:
                                chat_channel_id = chat['chatChannelId']
                            
                            message_time = chat['messageTime']
                            user_id_hash = chat['userIdHash']
                            content = chat.get('content', '')
                            message_type_code = chat.get('messageTypeCode', 1)
                            if user_id_hash == "anonymous":
                                user_id_hash = ""
                            
                            # 유닉스 타임스탬프를 한국 시간으로 변환
                            timestamp = message_time / 1000.0
                            kst = timezone(timedelta(hours=9))
                            kst_time = datetime.fromtimestamp(timestamp, kst)
                            formatted_date = kst_time.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # 프로필에서 닉네임 가져오기 및 사용자 정보 수집
                            nickname = "익명"
                            if chat.get('profile') and chat['profile'] != "null":
                                try:
                                    profile = json.loads(chat['profile'])
                                    nickname = profile.get("nickname", "Unknown")
                                    
                                    # 스트리머 닉네임 찾기
                                    if streamer_nickname is None and profile.get("userRoleCode") == "streamer":
                                        streamer_nickname = nickname
                                    
                                    # 사용자 상세 정보 수집 추가
                                    collect_user_info(user_id_hash, profile, user_details)
                                except (json.JSONDecodeError, AttributeError, TypeError):
                                    nickname = "Unknown"
                            
                            # 사용자 해시값 저장 (모든 경우에 저장)
                            #user_hashes[user_id_hash] = nickname
                            # 익명 사용자 필터링, 이후 사용자 해시값 저장
                            if nickname != "익명" and user_id_hash and user_id_hash != "":
                                if user_id_hash not in user_hashes:
                                    user_hashes[user_id_hash] = nickname
                            
                            # extras 데이터 파싱
                            extras_data = {}
                            if chat.get('extras'):
                                try:
                                    extras_data = json.loads(chat['extras'])
                                except (json.JSONDecodeError, TypeError):
                                    extras_data = {}
                            message_status_type = chat.get("messageStatusType", "")
                            if message_status_type == "HIDDEN":
                                # 검열된 메시지 처리
                                chat_log = f"[{formatted_date}] 오류 [??] {nickname} : <블라인드됨>"
                                file.write(f"{chat_log}\n")
                                continue
                            
                            # 메시지 유형 결정 (사용 안함)
                            #message_type = "채팅"
                            
                            # 메시지 타입 코드에 따른 분류
                            if message_type_code == 1:  # 일반 채팅
                                os_type = extras_data.get('osType', 'osX')
                                chat_log = f"[{formatted_date}] 채 [{os_type}] {nickname} : {content}"
                                #message_type = f"채 [{os_type}]"
                            elif message_type_code == 10:  # 후원
                                pay_amount = extras_data.get('payAmount', 0)
                                os_type = extras_data.get('osType', 'osX')
                                donation_type = extras_data.get("donationType", "알 수 없음")
                                
                                # donation_type에 따른 차별화된 메시지 처리
                                if donation_type == "CHAT":
                                    chat_log = f"[{formatted_date}] 후 [{pay_amount}원/{os_type}] {nickname} : {content}"
                                elif donation_type == "MISSION":
                                    mission_end_time = extras_data.get("missionEndTime", "알 수 없는 시간")
                                    mission_created_time = extras_data.get("missionCreatedTime", "알 수 없는 시간")
                                    #chat_log = f"[{formatted_date}] 미션후원 [{pay_amount}원 시작:{mission_created_time} 종료:{mission_end_time} {os_type}] {nickname}({user_id_hash}) : {content}"
                                    chat_log = f"[{formatted_date}] 후 [{pay_amount}원/미션후원_시작:{mission_created_time} 종료:{mission_end_time}] {nickname} : {content}"
                                elif donation_type == "MISSION_PARTICIPATION":
                                    #mission_title = extras_data.get("missionText", "알 수 없는 미션")
                                    total_pay_amount = extras_data.get("totalPayAmount", 0)
                                    #chat_log = f"[{formatted_date}] 미션참여 [{pay_amount}원{os_type}] {nickname}({user_id_hash}) : {content}"
                                    chat_log = f"[{formatted_date}] 후 [{pay_amount}원→{total_pay_amount}원/미션참여] {nickname} : {content}"
                                elif donation_type == "VIDEO":
                                    chat_log = f"[{formatted_date}] 후 [{pay_amount}원/영상후원/{os_type}] {nickname} : {content}"
                                elif donation_type == "PARTY":
                                    party_name = extras_data.get("partyName", "알 수 없음")
                                    chat_log = f"[{formatted_date}] 후 [{pay_amount}원/파티후원/{os_type}] {nickname} : {party_name}"
                                else:
                                    chat_log = f"[{formatted_date}] 후 [알 수 없는 타입:{donation_type} {pay_amount}원/{donation_type}/{os_type}] {nickname} : {content}"

                            elif message_type_code == 11:
                                # 구독 메시지
                                month = extras_data.get("month", 0)
                                tier_no = extras_data.get("tierNo", 1)
                                tier_name = extras_data.get("tierName", "일반")
                                
                                chat_log = f"[{formatted_date}] 구 [{month}월/티어{tier_no}:{tier_name}] {nickname} : {content}"
                            
                            elif message_type_code == 12:
                                # 구독 선물 메시지
                                gift_tier_no = extras_data.get("giftTierNo", 1)
                                gift_tier_name = extras_data.get("giftTierName", "일반")
                                receiver_nickname = extras_data.get("receiverNickname", "<무작위>")
                                quantity = extras_data.get("quantity", "알 수 없음")
                                giftType = extras_data.get("giftType", "알 수 없음")
                                
                                if giftType == "SUBSCRIPTION_GIFT":
                                    chat_log = f"[{formatted_date}] 구 [선물_티어{gift_tier_no}:{gift_tier_name}/{quantity}개] {nickname} → {receiver_nickname}{content}"
                                elif giftType == "SUBSCRIPTION_GIFT_RECEIVER":
                                    chat_log = f"[{formatted_date}] 구 [선물_티어{gift_tier_no}:{gift_tier_name}] {nickname} → {receiver_nickname}{content}"
                                else:
                                    chat_log = f"[{formatted_date}] 구 [알 수 없는 타입:{giftType} 선물_티어{gift_tier_no}:{gift_tier_name}/{quantity}개] {nickname} → {receiver_nickname}{content}"
                                    
                            # 기타 알 수 없는 메시지 유형
                            else:
                                chat_log = f"[{formatted_date}] 알 수 없음[타입:{message_type_code}] {nickname} : {content}"

                                #if "payAmount" in extras_data:
                                    #message_type = f"후 [{pay_amount}원]"
                                # 익명 후원인 경우
                                #if extras_data.get('anonymous', True):
                                    #nickname = "익명"
                            
                            # 구독 확인 (extras에 month가 있으면 구독)
                            #if extras_data.get('month'):
                                #message_type = f"구 [{extras_data.get('month')}월]"
                            
                            # 로그 메시지 생성 (해시값 포함)
                            #chat_log = f"[{formatted_date}] {message_type} {nickname} : {content} ({user_id_hash})\n"
                            
                            # 파일에 기록
                            file.write(f"{chat_log}\n")
                            
                        except Exception as chat_error:
                            # 개별 채팅 처리 중 오류 발생 시 해당 채팅만 건너뛰기
                            print(f"채팅 데이터 처리 중 오류 발생 (건너뜀): {chat_error}")
                            continue

                    # 다음 메시지 시간 설정
                    nextPlayerMessageTime = data['content']['nextPlayerMessageTime']

                    # 다음 메시지 시간이 null이면 크롤링 종료
                    if nextPlayerMessageTime is None:
                        print("마지막 채팅 페이지입니다. 데이터를 모두 파싱하고 종료합니다.")
                        break

                    print(f"채팅 페이지가 업데이트되었습니다. (nextPlayerMessageTime: {nextPlayerMessageTime})")

                else:
                    print("유효한 채팅 데이터가 없거나 요청이 완료되었습니다.")
                    break

        # 채팅 데이터가 수집된 경우에만 최적화 진행
        if chat_data_collected:
            # 최종 파일 경로 생성
            file_path = generate_final_file_path(streamer_nickname, chat_channel_id, vodId)
            # 임시 파일을 읽어서 최적화된 형태로 최종 파일에 저장
            optimize_chat_log(temp_file_path, file_path, user_hashes, user_details, vodId)
        else:
            print("수집된 채팅 데이터가 없습니다.")
        
    except requests.exceptions.RequestException as e:
        print(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
    except KeyError as e:
        print(f"JSON 파싱 중 오류가 발생했습니다: {e}")
    except Exception as e:
        print(f"예상치 못한 오류가 발생했습니다: {e}")
    finally:
        # 임시 파일이 존재하면 항상 삭제
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            if not chat_data_collected:
                print(f"오류로 인해 임시 파일 {temp_file_path}을 삭제했습니다.")

def generate_final_file_path(streamer_nickname, chat_channel_id, vodId):
    """최종 파일 경로 생성"""
    # 스트리머 닉네임이 없으면 "Unknown" 사용
    if not streamer_nickname:
        streamer_nickname = "Unknown"
    
    # 채팅 채널 ID가 없으면 "Unknown" 사용
    if not chat_channel_id:
        chat_channel_id = "Unknown"
    
    # 파일명에 사용할 수 없는 문자들을 안전한 문자로 치환
    safe_streamer_name = re.sub(r'[<>:"/\\|?*]', '_', streamer_nickname)
    safe_channel_id = re.sub(r'[<>:"/\\|?*]', '_', chat_channel_id)
    
    return os.path.join(LOG_PATH, f"chatLog-{safe_streamer_name}_{vodId}_{safe_channel_id}.log")
        
def collect_user_info(user_id_hash, profile_data, user_details):
    """사용자 정보 수집 및 저장"""
    nickname = profile_data.get("nickname", "익명")
    user_role_code = profile_data.get("userRoleCode", "common_user")
    
    # 구독 정보 추출
    streaming_property = profile_data.get("streamingProperty", {})
    subscription = streaming_property.get("subscription", {})
    accumulative_month = subscription.get("accumulativeMonth", 0)
    tier = subscription.get("tier", 0)
    
    # 배지 정보 추출 (viewerBadges)
    viewer_badges = profile_data.get("viewerBadges", [])
    badge_names = []
    
    for badge_info in viewer_badges:
        badge = badge_info.get("badge", {})
        badge_id = badge.get("badgeId", "")
        image_url = badge.get("imageUrl", "")
        
        # badgeId를 한글명으로 변환
        if badge_id == "donation_newbie":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_03.png":
                badge_names.append("하트")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_01.png":
                badge_names.append("하트-24H")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_02.png":
                badge_names.append("하트-10D")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/icon/fan.png":
                badge_names.append("하트-옛") #배지 개편 이후로 안쓰는 듯
            else:
                badge_names.append(image_url)
        elif badge_id == "donation_accumulate_amount_lv1":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/icon/cheese01.png":
                badge_names.append("십만")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/recent_cheese01.png":
                badge_names.append("십만R")
            else:
                badge_names.append(image_url)
        elif badge_id == "donation_accumulate_amount_lv2":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/icon/cheese02.png":
                badge_names.append("백만")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/recent_cheese02.png":
                badge_names.append("백만R")
            else:
                badge_names.append(image_url)
        elif badge_id == "donation_accumulate_amount_lv3":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/icon/cheese03.png":
                badge_names.append("천만")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/recent_cheese03.png":
                badge_names.append("천만R")
            else:
                badge_names.append(image_url)
        elif badge_id == "donation_accumulate_amount_lv4":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/icon/cheese04.png":
                badge_names.append("아마도 1억 회장님")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/recent_cheese04.png":
                badge_names.append("아마도 1억 회장님R")
            else:
                badge_names.append(image_url)
        elif badge_id == "subscription_gift_count_1":
            badge_names.append("선물-1")
        elif badge_id == "subscription_gift_count_10":
            badge_names.append("선물-10")
        elif badge_id == "subscription_gift_count_50":
            badge_names.append("선물-50")
        elif badge_id == "subscription_gift_count_100":
            badge_names.append("선물-100")
        elif badge_id == "subscription_gift_count_250":
            badge_names.append("선물-250")
        elif badge_id == "subscription_gift_count_500":
            badge_names.append("선물-500")
        elif badge_id == "subscription_gift_count_1000":
            badge_names.append("선물-1000")
        elif badge_id == "cheat_key":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_1m.png":
                badge_names.append("치트-1")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_2m.png":
                badge_names.append("치트-2")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_3m.png":
                badge_names.append("치트-3")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_6m.png":
                badge_names.append("치트-6")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_9m.png":
                badge_names.append("치트-9")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_12m.png":
                badge_names.append("치트-12")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_18m.png":
                badge_names.append("치트-18")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_24m.png":
                badge_names.append("치트-24")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_30m.png":
                badge_names.append("치트-30")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_36m.png":
                badge_names.append("치트-36")
            else:
                badge_names.append(image_url)
        elif badge_id == "subscription_founder":
            badge_names.append("설립")
        elif badge_id == "all_time_viewers_2024":
            badge_names.append("24-탑5")
        else:
            badge_names.append(badge_id)
    
    # 활성중인 배지 정보 추출 (activityBadges)
    activity_badges = profile_data.get("activityBadges", [])
    activity_badge_names = []
    
    for badge_info in activity_badges:
        badge_id = badge_info.get("badgeId", "")
        image_url = badge_info.get("imageUrl", "")
        
        # 동일한 로직으로 변환
        if badge_id == "donation_newbie":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_03.png":
                activity_badge_names.append("하트")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_01.png":
                activity_badge_names.append("하트-24H")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/fan_02.png":
                activity_badge_names.append("하트-10D")
        elif badge_id == "cheat_key":
            if image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_1m.png":
                activity_badge_names.append("치트-1")
            elif image_url == "https://ssl.pstatic.net/static/nng/glive/badge/cheatkey_6m.png":
                activity_badge_names.append("치트-6")
        # 기타 활성 배지들 추가 가능
    
    # 사용자 등급 한글명 변환
    user_role_display = ""
    if user_role_code == "streamer":
        user_role_display = "스트리머"
    elif user_role_code == "streaming_channel_manager":
        user_role_display = "관리자"
    elif user_role_code == "streaming_chat_manager":
        user_role_display = "챗관리"
    elif user_role_code != "common_user":
        user_role_display = user_role_code
    
    # 사용자 정보 저장
    user_info = {
        "nickname": nickname,
        "user_id_hash": user_id_hash,
        "accumulative_month": accumulative_month,
        "tier": tier,
        "badges": badge_names,
        "user_role_code": user_role_code,
        "user_role_display": user_role_display,
        "activity_badges": activity_badge_names
    }
    
    user_details[user_id_hash] = user_info

def optimize_chat_log(temp_file_path, final_file_path, user_hashes, user_details, vodId):
    """채팅 로그 파일을 최적화하여 저장"""
    try:
        # 임시 파일에서 채팅 로그 읽기
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            chat_logs = f.readlines()
        
        # 최종 파일 생성
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            # 헤더 정보 추가
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"CHZZK 다시보기 채팅 로그 - VOD ID: {vodId} - 생성 시간: {current_time}\n\n")
            
            # 참여 시청자 목록 추가 (상세 정보 포함)
            f.write(f"해당 채팅에 참여한 시청자 수: {len(user_hashes)}\n")
            
            # 사용자 목록을 닉네임 기준으로 정렬하여 추가 (상세 정보 표시)
            user_list = []
            for user_hash, nickname in user_hashes.items():
                if user_hash in user_details:
                    user_detail = user_details[user_hash]
                    user_info = f"{user_detail['nickname']} ({user_hash})"
                    
                    # 사용자 등급 정보 추가
                    if user_detail.get('user_role_display'):
                        user_info += f" [등급:{user_detail['user_role_display']}]"
                    
                    # 구독 정보 추가
                    if user_detail['accumulative_month'] > 0 and user_detail['tier'] > 0:
                        user_info += f" [구독:{user_detail['accumulative_month']}/티어:{user_detail['tier']}]"
                    
                    # 활성중인 배지 정보 추가
                    if user_detail.get('activity_badges'):
                        activity_badge_str = "/".join(user_detail['activity_badges'])
                        user_info += f" [활성배지:{activity_badge_str}]"
                    
                    # 배지 정보 추가
                    if user_detail['badges']:
                        badge_str = "/".join(user_detail['badges'])
                        user_info += f" [보유배지:{badge_str}]"
                    
                    user_list.append(user_info)
                else:
                    # 상세 정보가 없는 경우 기본 형태
                    user_list.append(f"{nickname} ({user_hash})")
            
            # 닉네임 기준으로 정렬
            user_list.sort()
            for user_info in user_list:
                f.write(f"{user_info}\n")
            
            # 빈 줄 추가
            f.write("\n")
            
            # 채팅 로그에서 해시값 제거하여 추가
            for log in chat_logs:
                # 정규식을 사용하여 마지막에 있는 해시값 부분 제거
                f.write(log)
        
        # 최종 파일 경로 중복 확인 및 처리
        base_file_path = final_file_path.replace('.log', '')
        counter = 1
        new_file_path = final_file_path
        
        while os.path.exists(new_file_path):
            new_file_path = f"{base_file_path} ({counter}).log"
            counter += 1
        
        # 임시 파일을 최종 파일로 이름 변경
        os.rename(temp_file_path, new_file_path)
        print(f"모든 채팅 로그가 최적화되어 {new_file_path}에 저장되었습니다.")
        
    except Exception as e:
        print(f"로그 최적화 중 오류가 발생했습니다: {e}")
        # 오류 발생 시 원본 파일을 이름만 변경
        base_file_path = final_file_path.replace('.log', '')
        counter = 1
        new_file_path = final_file_path
        
        while os.path.exists(new_file_path):
            new_file_path = f"{base_file_path} ({counter}).log"
            counter += 1
            
        os.rename(temp_file_path, new_file_path)
        print(f"오류로 인해 원본 로그의 이름을 {new_file_path}로 변경했습니다.")

def get_VOD_list(user):
    # Collect VODs
    page = 0
    VODs = []
    while (True):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/'
            }

            # 임시 파일에 먼저 저장
            url = f"https://api.chzzk.naver.com/service/v1/channels/{user}/videos?sortType=LATEST&pagingType=PAGE&page={page}&size=18&publishDateAt=&videoType="
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            VODs += data['content']['data']
            page += 1
            

        except requests.exceptions.RequestException as e:
            print(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
        except KeyError as e:
            print(f"JSON 파싱 중 오류가 발생했습니다: {e}")
        except Exception as e:
            print(f"예상치 못한 오류가 발생했습니다: {e}")
        finally:
            break

    # Make list
    rst = [{'id': VOD['videoNo'], 'title': f"[{VOD['publishDate']}]{VOD['videoTitle']}"} for VOD in VODs]
    return rst

def search_keyword(keyword):
    files = os.listdir(LOG_PATH)
    txt_files = [f for f in files if f.endswith('.log')]

    for txt in txt_files:
        print(f'\n<{txt}>\n' + '-'*40)

        path = os.path.join(LOG_PATH, txt)
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines:
            for k in keyword:
                if k in line:
                    print('\t'+line.strip())
                    break

if __name__ == "__main__":
    USER_ID = "7b9c6553913c755812ef2cd9fbe1dc5c" # 치지직, 영구꾸 햄스터, 하네 많관부
    KEYWORDS = ['아저씨']

    VODs = get_VOD_list(USER_ID) 
    for VOD in VODs:
        fetch_and_save_chat_data(VOD['id'])
    search_keyword(KEYWORDS)
