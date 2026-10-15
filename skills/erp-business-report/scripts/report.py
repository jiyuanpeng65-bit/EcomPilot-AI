"""Small deterministic ERP report helper, not an Agent framework. No ERP writes."""
import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CHINA = timezone(timedelta(hours=8), 'Asia/Shanghai')
BASE = Path(__file__).resolve().parent.parent


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def fmt(value):
    return '未知' if value is None else format(value.normalize(), 'f')


def dates(period, start=None, end=None, today=None):
    today = today or datetime.now(CHINA).date()
    if period == 'all-demo':
        return None, None
    if period == 'today':
        return today, today
    if period == 'yesterday':
        return today - timedelta(days=1), today - timedelta(days=1)
    if period == 'last7':
        return today - timedelta(days=6), today
    if period != 'range' or not start or not end:
        raise ValueError('指定范围需要 --start 和 --end（YYYY-MM-DD）')
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b:
        raise ValueError('开始日期不能晚于结束日期')
    return a, b


def analyze(snapshot, start=None, end=None, threshold=Decimal('20')):
    threshold = number(threshold)
    if threshold is None or threshold < 0:
        raise ValueError('库存阈值必须是非负有限数字')
    issues = []
    for kind in ('Item', 'Sales Order', 'Bin'):
        entry = snapshot.get(kind, {})
        if not entry.get('complete'):
            issues.append(f"{kind} 查询不完整（{entry.get('error') or 'UNKNOWN'}）")
    items = snapshot.get('Item', {}).get('rows', [])
    names = {r.get('item_code'): r.get('item_name') for r in items if r.get('item_code')}
    if any(not r.get('item_code') or not r.get('item_name') for r in items):
        issues.append('Item 的 SKU 或名称字段缺失')
    orders = []
    for row in snapshot.get('Sales Order', {}).get('rows', []):
        try:
            business_date = date.fromisoformat(row['transaction_date'])
        except (KeyError, TypeError, ValueError):
            issues.append(f"订单 {row.get('name', '未知')} 业务日期缺失或无效，不能核实统计区间")
            if start:
                continue
            business_date = None
        if start and not (start <= business_date <= end):
            issues.append(f"订单 {row.get('name', '未知')} 位于接口筛选区间外，未计入")
            continue
        orders.append(row)
    totals = defaultdict(Decimal)
    amount_incomplete = False
    statuses = Counter()
    concerns = []
    docstatuses = Counter()
    for row in orders:
        status = row.get('status') or '状态未知'
        statuses[status] += 1
        docstatus = row.get('docstatus')
        docstatuses[str(docstatus)] += 1
        # Draft and cancelled orders are not valid submitted order amounts.
        if docstatus == 1:
            amount, currency = number(row.get('grand_total')), row.get('currency')
            if amount is None or not isinstance(currency, str) or not currency.strip():
                amount_incomplete = True
                issues.append(f"订单 {row.get('name', '未知')} 金额或币种缺失")
            else:
                totals[currency] += amount
        elif docstatus not in (0, 2):
            amount_incomplete = True
            issues.append(f"订单 {row.get('name', '未知')} 单据状态缺失，金额未计入")
        if docstatus == 2:
            continue
        reasons = {
            'To Bill': '待开票，请核查开票事项',
            'To Deliver': '订单状态为待交付，请核查交付事项',
            'To Deliver and Bill': '订单状态为待交付及开票，请核查两项进度',
            'Overdue': 'ERP 标记逾期，请核查订单处理情况',
            'On Hold': '订单暂停，请核查原因',
            'Draft': '草稿订单，请核查是否应提交',
        }
        if status in reasons or status not in ('Completed', 'Closed', 'Cancelled'):
            reason = reasons.get(status, f'状态 {status}，需要进一步核查')
            progress = number(row.get('per_delivered'))
            if progress is not None:
                reason += f'；ERP 订单交付进度 {fmt(progress)}%'
            concerns.append({'order': row.get('name') or '编号未知', 'reason': reason})
    inventory = []
    seen_bins = set()
    sku_totals = {}
    for row in snapshot.get('Bin', {}).get('rows', []):
        sku, warehouse = row.get('item_code'), row.get('warehouse')
        key = (sku, warehouse)
        if not sku or not warehouse or key in seen_bins:
            issues.append('Bin 存在 SKU/仓库缺失或重复，相关记录未计入')
            continue
        seen_bins.add(key)
        actual, reserved = number(row.get('actual_qty')), number(row.get('reserved_qty'))
        if actual is None or reserved is None:
            issues.append(f'{sku} / {warehouse} 库存字段缺失')
        if sku not in names:
            issues.append(f'{sku} 商品名称未能关联（可能停用或读取范围受限）')
        inventory.append({'sku': sku, 'name': names.get(sku) or '名称未知', 'warehouse': warehouse,
                          'actual': fmt(actual), 'reserved': fmt(reserved),
                          'low': actual is not None and actual < threshold,
                          'zero': actual == Decimal(0)})
        group = sku_totals.setdefault(sku, {'actual': Decimal(0), 'reserved': Decimal(0), 'complete': True, 'warehouses': 0})
        group['warehouses'] += 1
        if actual is None or reserved is None:
            group['complete'] = False
        else:
            group['actual'] += actual
            group['reserved'] += reserved
    groups = {sku: {**r, 'actual': fmt(r['actual']) if r['complete'] else '未知',
                    'reserved': fmt(r['reserved']) if r['complete'] else '未知'} for sku, r in sku_totals.items()}
    return {'issues': list(dict.fromkeys(issues)), 'order_count': len(orders),
            'order_query_complete': snapshot.get('Sales Order', {}).get('complete', False),
            'amounts': {k: fmt(v) for k, v in sorted(totals.items())},
            'amount_incomplete': amount_incomplete,
            'docstatuses': dict(docstatuses), 'statuses': dict(statuses), 'concerns': concerns,
            'inventory': inventory, 'sku_totals': groups,
            'item_count': len(names), 'inventory_sku_count': len(sku_totals),
            'low_skus': sorted({r['sku'] for r in inventory if r['low']}),
            'zero_skus': sorted({r['sku'] for r in inventory if r['zero']}),
            'threshold': fmt(threshold), 'orders': orders}


def render(snapshot, result, start, end):
    stamp = snapshot.get('queried_at', '')
    try:
        stamp = datetime.fromisoformat(stamp).astimezone(CHINA).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        stamp = '未知'
    if start:
        scope = f'{start} 至 {end}（按订单 transaction_date）'
    else:
        actual_dates = sorted(r.get('transaction_date') for r in result['orders'] if r.get('transaction_date'))
        scope = '全部可读取演示公司数据'
        if actual_dates:
            scope += f'（订单业务日期 {actual_dates[0]} 至 {actual_dates[-1]}）'
        elif result['order_query_complete']:
            scope += '（无订单）'
    order_count = str(result['order_count']) if result['order_query_complete'] else f"已读取 {result['order_count']} 单，总数未知"
    amounts = '；'.join(f'{currency} {amount}' for currency, amount in result['amounts'].items())
    if not amounts:
        amounts = '0（无已提交有效订单）' if result['order_query_complete'] and not result['amount_incomplete'] else '未知'
    if result['amount_incomplete'] or not result['order_query_complete']:
        amounts += '（数据不完整，仅列已核实部分）'
    lines = ['【EcomPilot AI｜经营日报】', f'统计范围：{scope}', '时区：Asia/Shanghai（UTC+8）',
             f'数据更新时间：{stamp}', '', '一、订单概况', f'- 订单数量：{order_count}（含草稿/取消）',
             f'- 订单金额：{amounts}（仅已提交、未取消订单）',
             '- 主要订单状态：' + ('；'.join(f'{s} {n}单' for s, n in result['statuses'].items()) or ('无' if result['order_query_complete'] else '未知'))]
    concerns = result['concerns']
    lines.append(f'- 需要关注的订单：{len(concerns)} 单' + ('（仅已读取部分）' if not result['order_query_complete'] else ''))
    lines += [f"  {r['order']}：{r['reason']}" for r in concerns[:6]]
    if len(concerns) > 6:
        lines.append(f'  另 {len(concerns)-6} 单见本地详细结果')
    lines += ['', '二、库存概况', f"- 商品 SKU：已读取 {result['item_count']} 个；有库存记录 SKU {result['inventory_sku_count']} 个",
              f"- 低库存 SKU：{len(result['low_skus'])} 个（任一仓库实际库存 < {result['threshold']}）",
              f"- 零库存 SKU：{len(result['zero_skus'])} 个（任一仓库实际库存为 0）"]
    if not snapshot.get('Bin', {}).get('complete'):
        lines.append('- 库存查询不完整，上述仅为已读取记录；全量风险数未知')
    risk_rows = [r for r in result['inventory'] if r['low'] or r['zero']]
    shown = risk_rows if risk_rows else result['inventory']
    for row in shown[:8]:
        label = '零库存' if row['zero'] else '低库存' if row['low'] else '阈值内正常'
        if row['actual'] == '未知':
            label = '数据不完整'
        lines.append(f"  {row['sku']}｜{row['name']}｜{row['warehouse']}：实际 {row['actual']}，预留 {row['reserved']}（{label}）")
    if len(shown) > 8:
        lines.append(f'  另 {len(shown)-8} 条见本地详细结果')
    for sku, total in result['sku_totals'].items():
        if total['warehouses'] > 1:
            lines.append(f"  {sku} 跨仓汇总：实际 {total['actual']}，预留 {total['reserved']}，{total['warehouses']} 仓")
    lines += ['', '三、今日重点事项']
    actions = []
    if result['zero_skus']:
        actions.append('核查零库存仓库：' + '、'.join(result['zero_skus']))
    if result['low_skus']:
        actions.append(f"核查低库存记录（阈值 {result['threshold']}）：" + '、'.join(result['low_skus']))
    if concerns:
        actions.append('跟进订单：' + '、'.join(r['order'] for r in concerns[:6]))
    if result['issues']:
        actions.append('先处理数据不完整项目，不能按完整数据作决策')
    if not actions:
        actions.append('在本次已核实的订单与库存范围内，没有发现上述三类异常')
    lines += [f'{i}. {text}' for i, text in enumerate(actions, 1)]
    lines += ['', '四、数据说明', '- 来源：ERPNext 实时只读 API；库存是查询时账面快照，不是历史日期库存。',
              '- actual_qty 为账面实际库存，reserved_qty 为预留库存；没有计算准确可销售库存。',
              '- 订单金额不等于收款、利润或确认收入；不同币种分别统计。',
              '- 订单交付进度仅来自订单字段；未查询 Delivery Note、物流、收款、售后，不能据此确认实际发货或物流揽收。']
    lines += ['- 数据不完整：' + '；'.join(result['issues'])] if result['issues'] else ['- 三类查询均完成；本次没有发现缺失字段。']
    return '\n'.join(lines)


def collect(config, start, end):
    script = BASE / 'scripts' / 'fetch_erp.ps1'
    # Scope the policy to this child process; do not change machine/user settings.
    cmd = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Config', str(config)]
    if start:
        cmd += ['-StartDate', str(start), '-EndDate', str(end)]
    try:
        run = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=180)
        data = json.loads(run.stdout.lstrip('\ufeff'))
        if run.returncode or data.get('fatal') or not data.get('identity_verified'):
            raise ValueError('connection unavailable')
        return data
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise RuntimeError('只读连接不可用：检查 ERP 运行状态及授权的只读进程环境变量；禁止管理员回退') from None


def main():
    parser = argparse.ArgumentParser(description='每次实时 GET 查询 ERPNext，只读经营报表')
    parser.add_argument('--period', choices=['today', 'yesterday', 'last7', 'range', 'all-demo'], default='today')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--threshold', default='20')
    parser.add_argument('--config', type=Path, default=BASE / 'references' / 'runtime.json')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        if args.period != 'range' and (args.start or args.end):
            raise ValueError('起止日期仅用于 --period range')
        start, end = dates(args.period, args.start, args.end)
        threshold = number(args.threshold)
        if threshold is None or threshold < 0:
            raise ValueError('库存阈值必须是非负有限数字')
        snapshot = collect(args.config, start, end)
        result = analyze(snapshot, start, end, threshold)
        report = render(snapshot, result, start, end)
        report_id = 'ecp-' + hashlib.sha256(report.encode()).hexdigest()[:24]
        output = {'report_id': report_id, 'read_only': True, 'complete': not result['issues'],
                  'queried_at': snapshot['queried_at'], 'analysis': result, 'report': report}
        print(json.dumps(output, ensure_ascii=False) if args.json else report)
        return 0 if output['complete'] else 3
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc), 'complete': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
