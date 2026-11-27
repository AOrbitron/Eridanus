from datetime import datetime

from pydantic import AnyUrl as Url
import pprint

from .config import TEMPLATES_DIR, RES_DIR, Building_Dir, career_dir, card_img_dir
from .schemas import ArkCard, RogueData, EndfieldCard
from .filters import (
    loads_json,
    format_timestamp,
    time_to_next_4am,
    charId_to_avatarUrl,
    format_timestamp_str,
    charId_to_portraitUrl,
    time_to_next_monday_4am,
)
from framework_common.manshuo_draw import *

def rogue_totem(totem, topic):
    match topic:
        case 'rogue_1': img_url = f"run/anime_game_service\service\skland\core/resources/images/rogue/capsule/{totem.id}.png"
        case 'rogue_2': img_url = f"run/anime_game_service\service\skland\core/resources/images/rogue/mutation/pic_{totem.id}.png"
        case 'rogue_3': img_url = f"https://web.hycdn.cn/arknights/game/assets/roguelike_item/{totem.id}.png"
        case 'rogue_4': img_url = f"https://web.hycdn.cn/arknights/game/assets/roguelike_item/{totem.id}.png"
        case _: img_url = None
    return img_url

async def render_ark_card(props ,bg ):
    draw_data ={
            "now_ts": datetime.now().timestamp(),
            "background_image": bg,
            "status": props.status,
            "employed_chars": len(props.chars),
            "skins": len(props.skins),
            "building": props.building,
            "medals": props.medal.total,
            "assist_chars": props.assistChars,
            "recruit_finished": props.recruit_finished,
            "recruit_max": len(props.recruit),
            "recruit_complete_time": props.recruit_complete_time,
            "campaign": props.campaign,
            "routine": props.routine,
            "tower": props.tower,
            "training_char": props.trainee_char,
        }
    #pprint.pprint(draw_data)
    #for char in props.assistChars:print(char.portrait)
    #print(bg)

    img_path=await manshuo_draw(
        [{'type': 'basic_set','img_path_save':'data/pictures/cache','img_name_save':None,'img_height':2000,'font_common_color':(255,255,255),'font_title_color':(255,255,255),'font_des_color':(255,255,255),
          'backdrop_color':{'color1':'(80, 80, 80, 255)'},'stroke_layer_color':(130,130,130),'stroke_img_color':(130,130,130)},
         {'type': 'backdrop', 'subtype': 'gradient','left_color': (5,22,29),'right_color': (84,89,88)},
         {'type': 'avatar', 'img': [props.status.avatar.url],'upshift_extra': 20,'background':[bg],
         'content': [f"[name]{props.status.name}[/name] [time]lv:{props.status.level} [/time]\n"
                     f"[time]id:{props.status.uid} 入职日:{props.status.register_time} [/time]"]},
         {'type': 'img', 'subtype': 'common_with_des', 'number_per_row': 5,
         'is_shadow_img': False, 'description_color': (52, 52, 52, 255),
         'img': [(career_dir / 'career_1.png').as_posix(),(career_dir / 'career_2.png').as_posix(),
                 (career_dir / 'career_3.png').as_posix(),(career_dir / 'career_4.png').as_posix(),
                 (career_dir / 'career_5.png').as_posix(),],
         'content': [f'作战进度\n{props.status.mainStageProgress or "未公开"}',f'雇佣干员\n{len(props.chars)}',
                     f'时装数量\n{len(props.skins)}',f'家具保有\n{props.building.furniture.total}',
                     f'蚀刻章\n{props.medal.total}',]},
        '   ',{'type': 'text', 'content': ['[title]助战干员[/title]'],'layer':2},
        {'type':'img','is_crop':False,'img':[char.portrait for char in props.assistChars],'layer':2,
         'is_stroke_img':False, 'is_shadow_img':False, 'is_rounded_corners_img': False, 'number_per_row': 3,'jump_next_page':True},

        {'type': 'text', 'content': ['[title]基建信息[/title]'],'layer':2},
        {'type': 'img', 'subtype': 'common_with_des_right', 'number_per_row': 2,'layer': 2,
         'is_shadow_img':False,'magnification_img':8,'padding': 11,
         'description_color': (52, 52, 52, 255),
         'img': [(Building_Dir / 'labor.png').as_posix(),(Building_Dir / 'dorm.png').as_posix(),
                 (Building_Dir / 'trading.png').as_posix(), (Building_Dir / 'manufact.png').as_posix(),
                 (Building_Dir / 'tired.png').as_posix(),(Building_Dir / 'meeting.png').as_posix(),],
         'content':[f'无人机：{props.building.labor.labor_now} / {props.building.labor.maxValue}',
                    f'休息进度:{props.building.rested_chars} / {props.building.dorm_chars}',
                    f'订单进度:{props.building.trading_stock} / {props.building.trading_stock_limit}',
                    f'制造进度:{props.building.manufacture_stoke.current} / {props.building.manufacture_stoke.total}',
                    f'干员疲劳:{len(props.building.tiredChars) }',
                    f'线索交流:{len(props.building.meeting.clue.board) } / 7',]},
         '   ',
         {'type': 'img', 'subtype': 'common_with_des_right', 'number_per_row': 3,
          'is_shadow_img': False, 'description_color': (52, 52, 52, 255),
          'img': [(card_img_dir / 'ap.png').as_posix(), (card_img_dir / 'recruit.png').as_posix(),
                  (card_img_dir / 'hire.png').as_posix(), (card_img_dir / 'jade.png').as_posix(),
                  (card_img_dir / 'daily.png').as_posix(),(card_img_dir / 'weekly.png').as_posix(),
                  (card_img_dir / 'tower.png').as_posix(),(card_img_dir / 'tower.png').as_posix(),
                  (card_img_dir / 'train.png').as_posix(),],
          'content': [f'理智\n{props.status.ap.ap_now} / {props.status.ap.max}',
                      f'公开招募\n{props.recruit_finished} / {len(props.recruit)}',
                      f'公招刷新\n{props.building.hire.refreshCount} / 3',
                      f'剿灭奖励\n{props.campaign.reward.current} / {props.campaign.reward.total}',
                      f'每日任务\n{props.routine.daily.current} / {props.routine.daily.total}',
                      f'每周任务\n{props.routine.weekly.current} / {props.routine.weekly.total}',
                      f'数据增补仪\n{props.tower.reward.higherItem.current} / {props.tower.reward.higherItem.total}',
                      f'数据增补条\n{props.tower.reward.lowerItem.current} / {props.tower.reward.lowerItem.total}',
                      f'训练室\n{props.trainee_char}   {props.building.training.training_state}',
                      ]},
         '[des]                                             Function By 漫朔[/des]'
    ])
    return img_path


async def render_endfield_card(props: EndfieldCard, role: dict, bg: str | Url):
    """沿用明日方舟信息卡风格，展示终末地实时状态和活动模块。"""
    name = role.get("nickname") or "管理员"
    level = f"  Lv.{role['level']}" if role.get("level") is not None else ""
    draw_json = [
        {'type': 'basic_set', 'debug': False, 'img_height': 1100, 'img_path_save': 'data/pictures/cache', 'img_name_save': None,
         'font_common_color': (255, 255, 255), 'font_title_color': (255, 255, 255),
         'font_des_color': (210, 215, 220), 'backdrop_color': {'color1': '(80, 80, 80, 255)'},
         'stroke_layer_color': (130, 130, 130), 'stroke_img_color': (130, 130, 130)},
        {'type': 'backdrop', 'subtype': 'gradient', 'left_color': (5, 22, 29), 'right_color': (84, 89, 88)},
        {'type': 'avatar', 'img': [props.data.pic or str(bg)], 'upshift_extra': 20, 'background': [str(bg)],
         'content': [f"[name]{name}[/name] [time]{level}[/time]\n[time]UID:{role['roleid']}  终末地[/time]"]},
        {'type': 'text', 'content': [f'[title]每日信息[/title]\n[des]更新于 {props.updated_at}（北京时间）[/des]'], 'layer': 2},
    ]
    counters = props.counters
    icons = {item.name: item.icon for item in props.data.items if item.icon}
    draw_json.append({
        'type': 'img', 'subtype': 'common_with_des_right', 'number_per_row': 2, 'layer': 2,
        'is_shadow_img': False, 'magnification_img': 4, 'description_color': (52, 52, 52, 255),
        'img': [icons.get(title) or (card_img_dir / ('ap.png' if title == '体力' else 'daily.png')).as_posix()
                for title, _ in counters],
        'content': [f'{title}\n{value}' for title, value in counters],
    })
    draw_json.append({'type': 'text', 'content': [props.recovery], 'layer': 2})
    for item in props.data.items:
        if item.image.get('url'):
            draw_json.append({
                'type': 'img', 'subtype': 'common_with_des_right', 'img': [item.image['url']],
                'content': [item.name or '活动信息'], 'number_per_row': 1,
                'is_crop': False, 'is_shadow_img': False, 'magnification_img': 4,
                'description_color': (52, 52, 52, 255), 'layer': 2,
            })
    draw_json.append('[des]                                             function by manshuo[/des]')
    return await manshuo_draw(draw_json)


async def render_rogue_card(props: RogueData, bg: str | Url) -> bytes:
    draw_data ={
            "background_image": bg,
            "topic_img": props.topic_img,
            "topic": props.topic,
            "now_ts": datetime.now().timestamp(),
            "career": props.career,
            "game_user_info": props.gameUserInfo,
            "history": props.history,
        }
    #pprint.pprint(draw_data)

    rogue_favour_info, index=['    ',{'type': 'text', 'content': ['[title]收藏战绩[/title]'], 'layer': 2}], 0
    for record in props.history.favourRecords:
        if record.success:status = '胜利'
        else:status = '失败'
        index += 1
        per_rogue_info=[{'type': 'text', 'content': [f'[title]{record.mode} - {record.modeGrade}            {status}[/title]'
                                                     f'\n得分：{record.score}     {record.lastStage}'], 'layer': 3},
                        {'type': 'img', 'number_per_row': 8, 'layer': 3,'is_shadow_img': False,'img': [ charId_to_avatarUrl(char.id) for char in record.lastChars],},
                        {'type': 'text',
                         'content': [f'id：{index}     {format_timestamp_str(record.endTs)}'], 'layer': 3},
                        ]
        if index == 1:rogue_favour_info = rogue_favour_info + per_rogue_info
        else:rogue_favour_info = rogue_favour_info + [{'type': 'text', 'content': ['  '], 'layer': 2}] + per_rogue_info
    if index == 0:rogue_favour_info += [{'type': 'text', 'content': ['本人好像没有收藏过任何战绩喵～'], 'layer': 2}]

    rogue_history_info, index=['    ',{'type': 'text', 'content': ['[title]最近战绩[/title]'], 'layer': 2}], 0
    for record in props.history.records:
        if record.success:status = '胜利'
        else:status = '失败'
        index += 1
        per_rogue_info=[{'type': 'text', 'content': [f'[title]{record.mode} - {record.modeGrade}            {status}[/title]'
                                                     f'\n得分：{record.score}     {record.lastStage}'], 'layer': 3},
                        {'type': 'img', 'number_per_row': 8, 'layer': 3,'is_shadow_img': False,'img': [ charId_to_avatarUrl(char.id) for char in record.lastChars],},
                        {'type': 'text',
                         'content': [f'id：{index}     {format_timestamp_str(record.endTs)}'], 'layer': 3},
                        ]
        #print(per_rogue_info)
        if index == 1:rogue_history_info = rogue_history_info + per_rogue_info
        else:rogue_history_info = rogue_history_info + [{'type': 'text', 'content': ['  '], 'layer': 2}] + per_rogue_info


    draw_json=[
        {'type': 'basic_set','debug':False ,'img_height':2000,'font_common_color':(255,255,255),'font_title_color':(255,255,255),'font_des_color':(255,255,255),
          'backdrop_color':{'color1':'(80, 80, 80, 255)'},'stroke_layer_color':(130,130,130),'stroke_img_color':(130,130,130)},
        {'type': 'backdrop', 'subtype': 'gradient','left_color': (5,22,29),'right_color': (84,89,88)},
        {'type': 'avatar', 'img': [props.gameUserInfo.avatar.url],'upshift_extra': 20,'background':[bg],
         'content': [f"[name]{props.gameUserInfo.name}[/name] \n[time]lv:{props.gameUserInfo.level} [/time]"]},
        {'type': 'img', 'subtype': 'common_with_des', 'number_per_row': 1,'is_shadow_img': False, 'description_color': (52, 52, 52, 255),'img': [props.topic_img],
         'content': [f'[title]最高成就：{props.history.mode} - {props.history.modeGrade}（难度）\n等级：Lv.{props.history.bpLevel}\n得分:{props.history.score}[/title]']},
        {'type': 'text', 'content': ['[title]常用干员[/title]'], 'layer': 2},
        {'type': 'img', 'is_crop': False, 'img': [charId_to_portraitUrl(char.id) for char in props.history.chars], 'layer': 2,
          'is_stroke_img': False, 'is_shadow_img': False, 'is_rounded_corners_img': False, 'number_per_row': 3},
    ]
    draw_json = draw_json + rogue_favour_info + rogue_history_info
    draw_json+=['[des]                                             Function By 漫朔[/des]']
    #pprint.pprint(draw_json)
    img_path=await manshuo_draw(draw_json)
    return img_path


async def render_rogue_info(props: RogueData, bg: str | Url, id: int, is_favored: bool) -> bytes:
    draw_data ={
            "id": id,
            "record": props.history.favourRecords[id - 1]
            if is_favored and id - 1 < len(props.history.favourRecords)
            else (props.history.records[id - 1] if id - 1 < len(props.history.records) else None),
            "is_favored": is_favored,
            "background_image": bg,
            "topic_img": props.topic_img,
            "topic": props.topic,
            "now_ts": datetime.now().timestamp(),
            "career": props.career,
            "game_user_info": props.gameUserInfo,
            "history": props.history,
        }
    #pprint.pprint(draw_data)
    record=draw_data['record']
    if record.success:status = '胜利'
    else:status = '失败'
    match props.topic:
        case 'rogue_1': topic_name='剧目'
        case 'rogue_2': topic_name = '符号认知'
        case 'rogue_3': topic_name = '密文板'
        case 'rogue_4': topic_name = '思绪'
        case _: topic_name = '未知'
    time_record=format_timestamp_str(record.endTs)
    text_json=''
    for text_check in loads_json(record.endingText):
        if 'fontSize' in text_check:text_json += f"[title]{text_check['content']}[/title]"
        else:text_json += text_check['content']
    draw_json=[
        {'type': 'basic_set','debug':False ,'img_height':1500,'font_common_color':(255,255,255),'font_title_color':(255,255,255),'font_des_color':(255,255,255),
          'backdrop_color':{'color1':'(80, 80, 80, 255)'},'stroke_layer_color':(130,130,130),'stroke_img_color':(130,130,130)},
        {'type': 'backdrop', 'subtype': 'gradient','left_color': (5,22,29),'right_color': (84,89,88)},
        {'type': 'avatar', 'img': [props.gameUserInfo.avatar.url],'upshift_extra': 20,'background':[bg],
         'content': [f"[name]{props.gameUserInfo.name}[/name]"
                     f"\n[time]lv:{props.gameUserInfo.level} [/time]"]},
        {'type': 'img', 'subtype': 'common_with_des', 'number_per_row': 1,
         'is_shadow_img': False, 'description_color': (52, 52, 52, 255),
         'img': [props.topic_img],
         'content': [f'[title]{record.lastStage}      {status}[/title]\n得分：{record.score}\n[des]{time_record}   {record.mode} {record.modeGrade}  {record.band.name}[/des]']},
        {'type': 'text', 'content': ['[title]初始干员[/title]'], 'layer': 2},
        {'type': 'img', 'is_crop': False, 'img': [charId_to_portraitUrl(char.id) for char in record.initChars], 'layer': 2,
          'is_stroke_img': False, 'is_shadow_img': False, 'is_rounded_corners_img': False, 'number_per_row': 5},
        '  ',{'type': 'text', 'content': ['[title]历程回顾[/title]'], 'layer': 2},{'type': 'text', 'content': [f'{text_json}'], 'layer': 2},
        '  ',{'type': 'text', 'content': ['[title]招募干员[/title]'], 'layer': 2},
        {'type': 'img', 'is_crop': False, 'img': [charId_to_portraitUrl(char.id) for char in record.troopChars],'layer': 2,
         'is_stroke_img': False, 'is_shadow_img': False, 'is_rounded_corners_img': False, 'number_per_row': 8},
        '  ', {'type': 'text', 'content': ['[title]收藏品[/title]'], 'layer': 2},
        {'type': 'img', 'is_crop': False, 'img': [f"https://web.hycdn.cn/arknights/game/assets/roguelike_item/{relic}.png" for relic in record.gainRelicList],
         'layer': 2,'is_stroke_img': False, 'is_shadow_img': False, 'is_rounded_corners_img': False, 'number_per_row': 10},
        '  ', {'type': 'text', 'content': [f'[title]{topic_name}[/title]'], 'layer': 2},
        {'type': 'img', 'is_crop': False, 'img': [rogue_totem(totem, props.topic) for totem in record.totemList],
         'layer': 2,'is_stroke_img': False, 'is_shadow_img': False, 'is_rounded_corners_img': False, 'number_per_row': 10},
        '  ', {'type': 'text', 'content': [f'[title]数据统计[/title]'], 'layer': 2},
        {'type': 'text', 'content': [f'通过层数：{record.cntCrossedZone}  通过步数：{record.cntArrivedNode} 普通战斗次数：{record.cntBattleNormal} \n'
                                     f'精英战斗次数：{record.cntBattleElite}  领袖战斗次数：{record.cntBattleBoss}  获得物品数：{record.cntGainRelicItem}   招募干员次数：{record.cntRecruitUpgrade}'], 'layer': 2},
    ]

    draw_json+=['[des]                                             Function By 漫朔[/des]']
    img_path=await manshuo_draw(draw_json)
    return img_path
