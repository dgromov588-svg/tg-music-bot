import asyncio, math, os, secrets, sqlite3, time
from pathlib import Path
import httpx, isodate
from dotenv import load_dotenv

load_dotenv()
BOT=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
YT=os.getenv('YOUTUBE_API_KEY','').strip()
PUB=os.getenv('PUBLISH_CHAT_ID','').strip()
REG=os.getenv('YOUTUBE_REGION_CODE','UA').strip() or 'UA'
LANG=os.getenv('YOUTUBE_RELEVANCE_LANGUAGE','uk').strip() or 'uk'
POLL=int(os.getenv('POLLING_TIMEOUT','30'))
MAXR=int(os.getenv('SEARCH_MAX_RESULTS','10'))
TTL=int(os.getenv('CACHE_TTL_SECONDS','3600'))
DB=os.getenv('DATABASE_PATH','data/music_bot.db').strip() or 'data/music_bot.db'
if not BOT or not YT or not PUB: raise RuntimeError('Fill TELEGRAM_BOT_TOKEN, YOUTUBE_API_KEY, PUBLISH_CHAT_ID')
API=f'https://api.telegram.org/bot{BOT}'
Path(DB).parent.mkdir(parents=True, exist_ok=True)
conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
conn.execute('CREATE TABLE IF NOT EXISTS pub(id INTEGER PRIMARY KEY, video_id TEXT, title TEXT, channel TEXT, url TEXT, query TEXT, label TEXT, msg_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
conn.execute('CREATE INDEX IF NOT EXISTS ix_pub_video ON pub(video_id)'); conn.commit()
http=httpx.AsyncClient(timeout=25)
cache={}
HELP='''/orig query — найти оригинал\n/remix query — найти ремиксы\n/find query — показать лучший результат и кнопки\n/add query — сразу опубликовать оригинал в канал\n/history [N] — последние публикации\n/republish <video_id> — повторная публикация\n/help — помощь'''
NEG='remix live cover karaoke slowed reverb nightcore sped up lyrics 8d instrumental bass boosted'.split()
RPOS='remix edit mix mashup bootleg vip'.split()
RNEG='live cover karaoke lyrics'.split()
OFF=['official','official audio','topic','vevo']

def q1(sql,args=()): return conn.execute(sql,args).fetchone()
def qall(sql,args=()): return conn.execute(sql,args).fetchall()
def add_pub(v,t,c,u,q,l,m): conn.execute('INSERT INTO pub(video_id,title,channel,url,query,label,msg_id) VALUES(?,?,?,?,?,?,?)',(v,t,c,u,q,l,m)); conn.commit()

def norm(s): return ' '.join((s or '').lower().replace('—',' ').replace('-',' ').split())
def dur(v):
    try: return int(isodate.parse_duration(v).total_seconds()) if v else None
    except: return None

def score(title, channel, desc, secs, views, query, remix=False):
    h=norm(f'{title} {channel} {desc}'); t=norm(title); q=norm(query); sc=0.0
    toks=[x for x in q.split() if len(x)>1]
    sc += sum(18 for x in toks if x in t)
    if q and q in t: sc += 35
    if any(x in h for x in OFF): sc += 22
    if secs is not None:
        if 110<=secs<=420: sc += 16
        elif secs<60 or secs>900: sc -= 25
    if views:
        try: sc += min(12, math.log10(max(int(views),1))*2)
        except: pass
    if remix:
        sc += sum(20 for x in RPOS if x in h)
        sc -= sum(18 for x in RNEG if x in h)
    else:
        sc -= sum(30 for x in NEG if x in h)
        if 'official audio' in h or 'audio' in t: sc += 10
    return sc

async def tg(method,payload):
    r=await http.post(f'{API}/{method}', json=payload); r.raise_for_status(); j=r.json()
    if not j.get('ok'): raise RuntimeError(j)
    return j.get('result')

async def yt_search(query, remix=False):
    q=f"{query} remix OR edit OR mix" if remix else f"{query} -remix -live -cover -karaoke -slowed -reverb -nightcore"
    r=await http.get('https://www.googleapis.com/youtube/v3/search', params={'part':'snippet','q':q,'type':'video','videoCategoryId':'10','maxResults':str(MAXR),'regionCode':REG,'relevanceLanguage':LANG,'safeSearch':'none','key':YT}); r.raise_for_status(); items=r.json().get('items',[])
    ids=[x.get('id',{}).get('videoId') for x in items if x.get('id',{}).get('videoId')]
    info={}
    if ids:
        r=await http.get('https://www.googleapis.com/youtube/v3/videos', params={'part':'contentDetails,statistics','id':','.join(ids),'key':YT}); r.raise_for_status(); info={x.get('id'):x for x in r.json().get('items',[]) if x.get('id')}
    out=[]
    for it in items:
        vid=it.get('id',{}).get('videoId'); sn=it.get('snippet',{})
        if not vid: continue
        dt=info.get(vid,{})
        secs=dur(dt.get('contentDetails',{}).get('duration'))
        views=dt.get('statistics',{}).get('viewCount')
        out.append({'video_id':vid,'title':sn.get('title','Untitled'),'channel':sn.get('channelTitle','Unknown'),'url':f'https://www.youtube.com/watch?v={vid}','secs':secs,'views':int(views) if str(views).isdigit() else None,'score':score(sn.get('title',''),sn.get('channelTitle',''),sn.get('description',''),secs,views,query,remix)})
    return sorted(out,key=lambda x:x['score'],reverse=True)

async def bundle(query):
    cid=secrets.token_urlsafe(6); b={'id':cid,'query':query,'orig':await yt_search(query,False),'remix':await yt_search(query,True)}; cache[cid]=(time.time()+TTL,b); return b

def from_cache(cid):
    x=cache.get(cid)
    if not x or time.time()>x[0]: cache.pop(cid,None); return None
    return x[1]

def fmt_track(x,head,q):
    s=[head,'',x['title'],f"Канал: {x['channel']}"]
    if x['secs'] is not None: s.append(f"Длительность: {x['secs']//60}:{x['secs']%60:02d}")
    if x['views'] is not None: s.append(f"Просмотры: {x['views']:,}".replace(',',' '))
    s+= [f"Score: {x['score']:.1f}",f"Запрос: {q}",x['url']]
    return '\n'.join(s)

def kb(rows): return {'inline_keyboard':rows}

def dup_msg(r): return f"Этот ролик уже публиковался.\n\n{r['title']}\nКанал: {r['channel']}\nТип: {r['label']}\nvideo_id: {r['video_id']}\nПовтор: /republish {r['video_id']}\n{r['url']}"

async def publish(x,query,label,allow=False):
    old=q1('SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1',(x['video_id'],))
    if old and not allow: return {'status':'dup','row':old}
    post=await tg('sendMessage',{'chat_id':PUB,'text':f"🎵 Найден трек\n\n{x['title']}\nYouTube-канал: {x['channel']}\nТип: {label}\nЗапрос: {query}\n{x['url']}",'reply_markup':kb([[{'text':'Открыть в YouTube','url':x['url']}]]),'disable_web_page_preview':True})
    add_pub(x['video_id'],x['title'],x['channel'],x['url'],query,label,post.get('message_id'))
    return {'status':'ok','post':post}

async def on_msg(m):
    text=(m.get('text') or '').strip(); chat=m['chat']['id']
    if not text: return
    cmd,_,arg=text.partition(' '); cmd=cmd.split('@',1)[0].lower(); arg=arg.strip()
    if cmd in ['/start','/help']: return await tg('sendMessage',{'chat_id':chat,'text':HELP})
    if cmd=='/history':
        try: n=max(1,min(50,int(arg or '10')))
        except: return await tg('sendMessage',{'chat_id':chat,'text':'Пример: /history 10'})
        rows=qall('SELECT * FROM pub ORDER BY id DESC LIMIT ?',(n,))
        if not rows: return await tg('sendMessage',{'chat_id':chat,'text':'История публикаций пока пустая.'})
        s=['Последние публикации: '+str(len(rows)),'']
        for i,r in enumerate(rows,1): s += [f"{i}. {r['title']}",f"   Тип: {r['label']} | video_id: {r['video_id']}",f"   Канал: {r['channel']}",f"   Дата: {r['created_at']}",'']
        return await tg('sendMessage',{'chat_id':chat,'text':'\n'.join(s).strip(),'disable_web_page_preview':True})
    if cmd=='/republish':
        if not arg: return await tg('sendMessage',{'chat_id':chat,'text':'Пример: /republish dQw4w9WgXcQ'})
        r=q1('SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1',(arg,))
        if not r: return await tg('sendMessage',{'chat_id':chat,'text':'Такого video_id нет в истории.'})
        x={'video_id':r['video_id'],'title':r['title'],'channel':r['channel'],'url':r['url']}
        await publish(x,r['query'],str(r['label'])+'_REPUBLISH',True)
        return await tg('sendMessage',{'chat_id':chat,'text':f"Переопубликовал:\n{r['title']}\n{r['url']}"})
    if cmd not in ['/orig','/remix','/find','/add'] or not arg:
        return await tg('sendMessage',{'chat_id':chat,'text':'Используй /help'})
    b=await bundle(arg)
    if cmd=='/remix':
        if not b['remix']: return await tg('sendMessage',{'chat_id':chat,'text':'Ремиксы не нашёл.'})
        s=[f"Ремиксы по запросу: {arg}",'']
        for i,x in enumerate(b['remix'][:3],1): s += [f"{i}. {x['title']}",f"   Канал: {x['channel']}",f"   Score: {x['score']:.1f}",f"   {x['url']}",'']
        rows=[[{'text':'Открыть 1','url':b['remix'][0]['url']}]]+[[{'text':f'Опубликовать remix {i+1}','callback_data':f"pubr|{b['id']}|{i}"}] for i,_ in enumerate(b['remix'][:3])]
        return await tg('sendMessage',{'chat_id':chat,'text':'\n'.join(s).strip(),'reply_markup':kb(rows),'disable_web_page_preview':True})
    if not b['orig']: return await tg('sendMessage',{'chat_id':chat,'text':'Ничего не нашёл по этому запросу.'})
    best=b['orig'][0]
    if cmd=='/add':
        res=await publish(best,arg,'ORIGINAL',False)
        if res['status']=='dup': return await tg('sendMessage',{'chat_id':chat,'text':dup_msg(res['row']),'reply_markup':kb([[{'text':'Открыть','url':res['row']['url']}]]),'disable_web_page_preview':True})
        return await tg('sendMessage',{'chat_id':chat,'text':f"Опубликовал в канал.\n\n{best['title']}\nКанал: {best['channel']}\nvideo_id: {best['video_id']}\nmessage_id: {res['post'].get('message_id')}\n{best['url']}",'reply_markup':kb([[{'text':'Открыть в YouTube','url':best['url']}]]),'disable_web_page_preview':True})
    return await tg('sendMessage',{'chat_id':chat,'text':fmt_track(best,'Лучший оригинал',arg),'reply_markup':kb([[{'text':'Открыть','url':best['url']}],[{'text':'Показать ремиксы','callback_data':f"showr|{b['id']}"}],[{'text':'Опубликовать оригинал','callback_data':f"pubo|{b['id']}"}]]),'disable_web_page_preview':True})

async def on_cb(c):
    cid=c['id']; data=c.get('data',''); msg=c.get('message') or {}; chat=msg.get('chat',{}).get('id'); p=data.split('|')
    if len(p)<2: return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Некорректная кнопка','show_alert':True})
    act,bid=p[0],p[1]; b=from_cache(bid)
    if not b: return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Кэш истёк, повтори поиск','show_alert':True})
    try:
        if act=='showr':
            await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Показываю ремиксы'})
            return await on_msg({'chat':{'id':chat},'text':'/remix '+b['query']})
        if act=='pubo':
            res=await publish(b['orig'][0],b['query'],'ORIGINAL',False)
            if res['status']=='dup':
                await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Уже был опубликован','show_alert':True})
                return await tg('sendMessage',{'chat_id':chat,'text':dup_msg(res['row']),'reply_markup':kb([[{'text':'Открыть','url':res['row']['url']}]]),'disable_web_page_preview':True})
            return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Оригинал опубликован'})
        if act=='pubr':
            i=int(p[2]) if len(p)>2 else 0
            if i>=len(b['remix']): return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Ремикс не найден','show_alert':True})
            res=await publish(b['remix'][i],b['query'],'REMIX',False)
            if res['status']=='dup':
                await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Уже был опубликован','show_alert':True})
                return await tg('sendMessage',{'chat_id':chat,'text':dup_msg(res['row']),'reply_markup':kb([[{'text':'Открыть','url':res['row']['url']}]]),'disable_web_page_preview':True})
            return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Ремикс опубликован'})
    except Exception:
        return await tg('answerCallbackQuery',{'callback_query_id':cid,'text':'Ошибка. Проверь права бота и лог','show_alert':True})

async def main():
    await tg('setMyCommands',{'commands':[{'command':'orig','description':'Найти оригинал трека'},{'command':'remix','description':'Найти ремиксы'},{'command':'find','description':'Найти трек и показать кнопки'},{'command':'add','description':'Опубликовать оригинал в канал'},{'command':'history','description':'Показать историю публикаций'},{'command':'republish','description':'Переопубликовать по video_id'},{'command':'help','description':'Показать помощь'}]})
    off=None
    while True:
        try:
            upd=await tg('getUpdates',{'offset':off,'timeout':POLL,'allowed_updates':['message','callback_query']})
            for u in upd:
                off=u['update_id']+1
                if 'message' in u: await on_msg(u['message'])
                elif 'callback_query' in u: await on_cb(u['callback_query'])
        except Exception:
            await asyncio.sleep(3)

asyncio.run(main())
