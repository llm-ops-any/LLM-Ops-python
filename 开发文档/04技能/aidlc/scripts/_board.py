#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总的「看板」：一页可筛选的 HTML（按人 / 时间 / 阶段 / 类型）。

为什么单独一个文件而不是塞进 `预览.py`：
  `预览.py` 已经是 22 KB（接近单文件 25 KB 上限），而看板要内嵌一段 JS + 样式，
  塞进去必然超限。看板只吃 `汇总.py` 的 `rows`，不重新解析 markdown —— 解析只有一套。

产物：`开发文档/_汇总/看板.html`，单文件、无外部依赖、可离线、可整份拷走。
跳转链接指向 `docs/<类型目录>/<CR 目录>/<状态文件>`，需要 `汇总.py --site` 生成过 docs/ 才有效。
"""

import io
import json
import os

from _aidlc_common import find_audit_files, find_cr_file
from _views_base import DOC, KIND_DIR

# 阶段中文标签：与 `汇总.py` 的 STAGE_LABEL 保持一致（那边是给 md 视图用的）
STAGE_LABEL = {
    'delivered': '已交付',
    'in-progress': '进行中',
    'awaiting-approval': '待批',
    'blocked': '阻塞',
    'fixed': '已修复',
    'not-started': '未开始',
    'cancelled': '已撤回',
}

KIND_ORDER = {'需求': 0, '缺陷': 1, '技术债': 2}

# 中文说法 → 标准标识。历史 CR 的「阶段」字段写法很杂：有 `delivered（待人工自测）`，
# 也有整句 `CONSTRUCTION · **已交付**（代码 + 产物齐全）`。不归一的话：
# 筛选下拉全是长句、CSS 的 `st-<阶段>` 也挂不上，筛选等于废的。
CN_TO_KEY = (
    ('已交付', 'delivered'), ('已完成', 'delivered'), ('完成', 'delivered'),
    ('已修复', 'fixed'), ('进行中', 'in-progress'), ('待批', 'awaiting-approval'),
    ('阻塞', 'blocked'), ('未开始', 'not-started'), ('已撤回', 'cancelled'), ('撤回', 'cancelled'),
)


def stage_key(v):
    """把各种写法的阶段归一成标准标识；认不出返回 'other'。"""
    s = (v or '').strip()
    low = s.lower()
    for key in STAGE_LABEL:                 # 英文标识优先
        if key in low:
            return key
    for cn, key in CN_TO_KEY:
        if cn in s:
            return key
    return 'other'


def stage_name(v):
    """给筛选下拉用的展示名：标准阶段给中文，认不出的统一显示「其他」。"""
    k = stage_key(v)
    if k != 'other':
        return STAGE_LABEL[k]
    # 认不出的（有人把阶段写成了整句）统一显示「其他」，原文放 title 悬停看。
    # 这里不猜语义 —— 猜错比显示「其他」更糟，数据该由人去改。
    return '其他'


def _audit_stat(cr_dir):
    """返回 {'count': 记录条数, 'people': {人: 条数}}。

    记录条数按审计文件里的 `## ` 小节数算 —— 那是「一条审计」的写法约定。
    文件本身也算证据：一个文件 + 0 条记录说明这人开了头没写内容。
    """
    people = {}
    total = 0
    for p in find_audit_files(cr_dir):
        who = os.path.basename(p).replace('40-审计-', '').replace('审计-', '').rsplit('.md', 1)[0]
        try:
            text = io.open(p, encoding='utf-8').read()
        except Exception:
            text = ''
        n = sum(1 for l in text.splitlines() if l.startswith('## ') and l.strip() != '## ')
        people[who] = people.get(who, 0) + n
        total += n
    return {'count': total, 'people': people}


def collect_board(rows):
    """把 rows 转成看板要的前端数据（纯 dict，能直接 json.dumps）。"""
    out = []
    for r in rows:
        st = find_cr_file(r['path'], '状态')
        href = ''
        if st:
            rel = os.path.relpath(st, DOC).replace(os.sep, '/')
            href = 'docs/' + rel
        a = _audit_stat(r['path'])
        out.append({
            'no': r.get('no') or '',
            'name': r.get('name') or '',
            'owner': r.get('owner') or '—',
            'kind': r['kind'],
            'kindDir': KIND_DIR[r['kind']],
            'dir': r['dir'],
            'stage': stage_key(r.get('stage')),
            'stageRaw': r.get('stage') or '—',
            'stageLabel': stage_name(r.get('stage')),
            'gate': r.get('gate') or '—',
            'created': r.get('created') or '',
            'updated': r.get('updated') or '',
            'next': r.get('next') or '—',
            'nature': r.get('nature') or '—',
            'audit': a['count'],
            'auditPeople': a['people'],
            'href': href,
        })
    return out


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s · 看板</title>
<style>
  :root{--ink:#1e293b;--dim:#64748b;--line:#e2e8f0;--bg:#f8fafc;--pri:#2563eb;--warn:#ea580c;}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.55 "Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:#fff}
  header{padding:18px 22px 12px;border-bottom:1px solid var(--line)}
  h1{margin:0 0 4px;font-size:19px;font-weight:600}
  .sub{color:var(--dim);font-size:12px}
  .wrap{padding:14px 22px 40px}
  .people{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
  .chip{border:1px solid var(--line);background:var(--bg);border-radius:14px;padding:4px 11px;
        font-size:12px;cursor:pointer;color:var(--ink)}
  .chip:hover{border-color:var(--pri);color:var(--pri)}
  .chip.on{background:var(--pri);border-color:var(--pri);color:#fff}
  .chip b{font-weight:600}
  .chip span{color:var(--dim);margin-left:4px}
  .chip.on span{color:#dbeafe}
  .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin:0 0 12px;
       padding:12px;background:var(--bg);border:1px solid var(--line);border-radius:8px}
  .f{display:flex;flex-direction:column;gap:3px}
  .f label{font-size:11px;color:var(--dim)}
  .f input,.f select{font:inherit;font-size:13px;padding:4px 7px;border:1px solid #cbd5e1;
                     border-radius:5px;background:#fff;color:var(--ink);min-width:104px}
  .f input[type=date]{min-width:132px}
  .grow{flex:1;min-width:160px}
  .grow input{width:100%%}
  button{font:inherit;font-size:13px;padding:5px 13px;border:1px solid #cbd5e1;border-radius:5px;
         background:#fff;cursor:pointer;color:var(--ink)}
  button:hover{border-color:var(--pri);color:var(--pri)}
  .meta{color:var(--dim);font-size:12px;margin:0 0 8px}
  .meta b{color:var(--ink)}
  table{width:100%%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  th{background:var(--bg);font-weight:600;font-size:12px;color:var(--dim);position:sticky;top:0;z-index:1}
  tbody tr:hover{background:#f1f5f9}
  tbody tr{cursor:pointer}
  td.no{font-family:Consolas,monospace;white-space:nowrap;font-size:12px}
  td.nowrap{white-space:nowrap}
  td.next{max-width:340px;color:var(--dim)}
  .tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--line);
       background:#fff;white-space:nowrap}
  .k-需求{border-color:#bfdbfe;background:#eff6ff;color:#1d4ed8}
  .k-缺陷{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
  .k-技术债{border-color:#e2e8f0;background:#f8fafc;color:#475569}
  .st-delivered{color:#15803d}
  .st-in-progress{color:var(--pri)}
  .st-blocked,.st-cancelled{color:var(--warn)}
  .st-not-started{color:var(--dim)}
  .st-other{color:var(--dim);border-bottom:1px dotted #cbd5e1;cursor:help}
  .empty{padding:26px;text-align:center;color:var(--dim);border:1px dashed var(--line);border-radius:8px}
  .note{margin-top:14px;color:var(--dim);font-size:12px}
  code{font-family:Consolas,monospace;background:var(--bg);padding:1px 4px;border-radius:3px}
  @media print{.bar,.people,button{display:none}th{position:static}tbody tr{cursor:auto}}
</style>
</head>
<body>
<header>
  <h1>%(title)s · CR 看板</h1>
  <div class="sub">生成时间 %(stamp)s ｜ 共 <b>%(total)d</b> 条 CR ｜ 点任意一行打开该 CR 的状态文件</div>
</header>
<div class="wrap">
  <div class="people" id="people"></div>
  <div class="bar">
    <div class="f"><label>负责人</label><select id="owner"></select></div>
    <div class="f"><label>类型</label><select id="kind"></select></div>
    <div class="f"><label>阶段</label><select id="stage"></select></div>
    <div class="f"><label>时间基准</label>
      <select id="basis"><option value="created">创建</option><option value="updated">更新</option></select>
    </div>
    <div class="f"><label>从</label><input type="date" id="from"></div>
    <div class="f"><label>到</label><input type="date" id="to"></div>
    <div class="f grow"><label>关键词（编号 / 名称 / 下一步）</label><input id="kw" placeholder="如：部署、搜索、CR-1610"></div>
    <button id="reset">重置</button>
  </div>
  <div class="meta" id="meta"></div>
  <table>
    <thead><tr>
      <th>编号</th><th>名称</th><th>负责人</th><th>类型</th><th>阶段</th>
      <th>创建</th><th>更新</th><th>审计</th><th>下一步</th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>
  <div class="empty" id="empty" style="display:none">没有符合条件的 CR —— 放宽筛选或点「重置」</div>
  <div class="note">
    数据来自各 CR 的 <code>00-状态.md</code>（负责人 / 时间 / 阶段）与 <code>40-审计-&lt;人&gt;.md</code>（审计条数）。
    本页由 <code>汇总.py</code> 生成，<b>不要手改</b>。跳转需要 <code>汇总.py --site</code> 生成过 <code>docs/</code>。
  </div>
</div>
<script>
var DATA = %(data)s;
var STAGES = %(stages)s;

function uniq(k){var s={};DATA.forEach(function(r){s[r[k]]=1});return Object.keys(s).sort()}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function day(s){return (s||'').slice(0,10)}

/* 顶部人物 chips：CR 数 + 审计条数，点一下即按该人筛 */
function renderPeople(){
  var box=document.getElementById('people'), m={};
  DATA.forEach(function(r){
    var o=r.owner||'—';
    m[o]=m[o]||{cr:0,au:0};
    m[o].cr++; m[o].au+=r.audit||0;
  });
  var keys=Object.keys(m).sort();
  var html='<div class="chip" data-o="">全部<b>'+DATA.length+'</b> 条</div>';
  keys.forEach(function(k){
    html+='<div class="chip" data-o="'+esc(k)+'">'+esc(k)+
          '<b>'+m[k].cr+'</b> 条<span>审计 '+m[k].au+'</span></div>';
  });
  box.innerHTML=html;
  Array.prototype.forEach.call(box.children,function(c){
    c.onclick=function(){
      document.getElementById('owner').value=c.getAttribute('data-o');
      apply();
    };
  });
}

function fillSel(id,vals,all){
  var el=document.getElementById(id);
  el.innerHTML='<option value="">'+all+'</option>'+vals.map(function(v){
    return '<option value="'+esc(v)+'">'+esc(v)+'</option>'}).join('');
}

function apply(){
  var o=document.getElementById('owner').value;
  var k=document.getElementById('kind').value;
  var st=document.getElementById('stage').value;
  var basis=document.getElementById('basis').value;
  var f=document.getElementById('from').value;
  var t=document.getElementById('to').value;
  var kw=document.getElementById('kw').value.trim().toLowerCase();

  var list=DATA.filter(function(r){
    if(o && (r.owner||'—')!==o) return false;
    if(k && r.kind!==k) return false;
    if(st && (r.stageLabel||r.stage)!==st) return false;
    var d=day(r[basis]);
    if(f && (!d || d<f)) return false;
    if(t && (!d || d>t)) return false;
    if(kw){
      var hay=(r.no+' '+r.name+' '+r.next).toLowerCase();
      if(hay.indexOf(kw)<0) return false;
    }
    return true;
  });

  var tb=document.getElementById('tb');
  if(!list.length){tb.innerHTML='';document.getElementById('empty').style.display='block';}
  else{
    document.getElementById('empty').style.display='none';
    tb.innerHTML=list.map(function(r){
      var href=r.href?' data-h="'+esc(r.href)+'"':'';
      return '<tr'+href+'>'+
        '<td class="no">'+esc(r.no)+'</td>'+
        '<td>'+esc(r.name)+'</td>'+
        '<td class="nowrap">'+esc(r.owner||'—')+'</td>'+
        '<td><span class="tag k-'+esc(r.kind)+'">'+esc(r.kind)+'</span></td>'+
        '<td class="st-'+esc(r.stage)+'" title="'+esc(r.stageRaw||'')+'">'+esc(r.stageLabel||r.stage)+'</td>'+
        '<td class="nowrap">'+esc(r.created||'—')+'</td>'+
        '<td class="nowrap">'+esc(r.updated||'—')+'</td>'+
        '<td class="nowrap">'+(r.audit||0)+'</td>'+
        '<td class="next">'+esc(r.next||'—')+'</td>'+
      '</tr>';
    }).join('');
    Array.prototype.forEach.call(tb.children,function(tr){
      tr.onclick=function(){
        var h=tr.getAttribute('data-h');
        if(h) location.href=h;
      };
    });
  }
  /* 人物 chip 高亮跟随筛选 */
  Array.prototype.forEach.call(document.getElementById('people').children,function(c){
    c.className='chip'+((c.getAttribute('data-o')||'')===o?' on':'');
  });
  document.getElementById('meta').innerHTML='显示 <b>'+list.length+'</b> / '+DATA.length+' 条';
}

renderPeople();
fillSel('owner',uniq('owner'),'全部负责人');
fillSel('kind',uniq('kind'),'全部类型');
fillSel('stage',STAGES,'全部阶段');
['owner','kind','stage','basis','from','to','kw'].forEach(function(id){
  var el=document.getElementById(id);
  el.oninput=apply; el.onchange=apply;
});
document.getElementById('reset').onclick=function(){
  ['owner','kind','stage','basis','from','to','kw'].forEach(function(id){
    document.getElementById(id).value='';
  });
  apply();
};
apply();
</script>
</body>
</html>
"""


def render_board(rows, stamp, title=None):
    """生成看板 HTML 全文。`rows` 是 `汇总.py` 的 collect() 结果。"""
    data = collect_board(rows)
    stages = sorted({r['stageLabel'] for r in data if r['stageLabel']})
    return PAGE % {
        'title': title or os.path.basename(os.path.dirname(DOC)),
        'stamp': stamp,
        'total': len(data),
        'data': json.dumps(data, ensure_ascii=False).replace('</', '<\\/'),
        'stages': json.dumps(stages, ensure_ascii=False),
    }
