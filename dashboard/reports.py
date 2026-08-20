"""PDF report generation for Sauron Vision."""
import io
import logging
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


@login_required
def generate_portfolio_report(request):
    """Generate a PDF portfolio performance report."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch, cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from portfolio.services import (get_or_create_default_portfolio,
                                    live_book_value)
    from portfolio.models import PortfolioSnapshot
    from signals.models import Signal
    from strategies.models import Strategy

    portfolio = get_or_create_default_portfolio(user=request.user)
    # Cash plus BOTH position books at live marks. The report printed
    # `Portfolio.current_value` — a stored column an hourly task writes from
    # the legacy book alone — so on an account whose positions are bot trades
    # every PDF ever exported said the book was worth its seeded capital, and
    # the TOTAL RETURN line under it said +0.00%. A PDF outlives the screen it
    # was taken from, which makes a frozen figure in one worse, not better.
    book = live_book_value(request.user, portfolio)
    now = timezone.now()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*cm, bottomMargin=1*cm)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle('SauronTitle', parent=styles['Title'], fontSize=20, textColor=colors.HexColor('#c0392b'))
    subtitle_style = ParagraphStyle('SauronSubtitle', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#e74c3c'))

    elements = []

    # Header
    elements.append(Paragraph("SAURON VISION", title_style))
    elements.append(Paragraph(f"Portfolio Report — {now.strftime('%B %d, %Y')}", subtitle_style))
    elements.append(Spacer(1, 0.3*inch))
    elements.append(HRFlowable(width="100%", color=colors.HexColor('#c0392b')))
    elements.append(Spacer(1, 0.2*inch))

    # Portfolio Summary
    # An em-dash where nothing could be measured, exactly as on screen: a
    # printed 0.00 is indistinguishable from a real flat book, and the reader
    # of a PDF cannot hover a tooltip to find out which it was.
    DASH = "—"
    elements.append(Paragraph("Portfolio Summary", styles['Heading2']))
    summary_data = [
        ['Metric', 'Value'],
        ['Portfolio Value',
         DASH if book.value is None
         else f"{portfolio.currency} {book.value:,.2f}"],
        ['Cash Available', f"{portfolio.currency} {portfolio.cash_available:,.2f}"],
        ['Initial Capital', f"{portfolio.currency} {portfolio.initial_capital:,.2f}"],
        ['Open Positions',
         f"{book.n_open} ({book.n_priced} priced)" if book.n_open else "0"],
    ]

    # Calculate return
    if portfolio.initial_capital > 0:
        if book.value is None:
            summary_data.append(['Total Return', DASH])
        else:
            total_return = ((book.value - float(portfolio.initial_capital))
                            / float(portfolio.initial_capital)) * 100
            summary_data.append(['Total Return', f"{total_return:+.2f}%"])

    # The basis line, so a reader can tell a whole-book figure from a partial
    # one months after the export — the same sentence the screens carry. A
    # Paragraph and not a bare string: a plain cell does not wrap, and this
    # sentence is wider than the 3-inch column it sits in.
    summary_data.append(['Valuation Basis',
                         Paragraph(book.coverage, styles['BodyText'])])

    t = Table(summary_data, colWidths=[3*inch, 3*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8f9fa'), colors.white]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3*inch))

    # Open Positions — BOTH books, already marked by `live_book_value`. This
    # queried portfolio.Position alone, so every bot entry and every TAKE
    # TRADE was missing from the export; and it formatted current_price with
    # ":.4f", which raises on the None an unquoted row carries, so a single
    # symbol without a quote took the whole PDF down with a TypeError.
    open_positions = book.rows
    if open_positions:
        elements.append(Paragraph("Open Positions", styles['Heading2']))
        pos_data = [['Symbol', 'Direction', 'Qty', 'Entry', 'Current', 'P&L %']]
        for p in open_positions[:20]:
            pos_data.append([
                getattr(p.instrument, "symbol", "") or DASH,
                p.direction, f"{p.quantity}",
                f"{float(p.entry_price):.4f}" if p.entry_price is not None else DASH,
                f"{float(p.current_price):.4f}" if p.current_price is not None else DASH,
                (f"{float(p.unrealized_pnl_pct):+.2f}%"
                 if p.unrealized_pnl_pct is not None else DASH),
            ])
        t2 = Table(pos_data, colWidths=[1.2*inch, 0.8*inch, 0.8*inch, 1.2*inch, 1.2*inch, 0.8*inch])
        t2.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8f9fa'), colors.white]),
        ]))
        elements.append(t2)
        elements.append(Spacer(1, 0.3*inch))

    # Active Signals
    active_signals = Signal.objects.filter(is_active=True).select_related('instrument').order_by('-score')[:10]
    if active_signals:
        elements.append(Paragraph("Active Signals (Top 10)", styles['Heading2']))
        sig_data = [['Symbol', 'Type', 'Direction', 'Score', 'Urgency']]
        for s in active_signals:
            sig_data.append([s.instrument.symbol, s.signal_type, s.direction, f"{s.score:.2f}", s.urgency])
        t3 = Table(sig_data, colWidths=[1.2*inch, 1.2*inch, 1*inch, 0.8*inch, 0.8*inch])
        t3.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t3)
        elements.append(Spacer(1, 0.3*inch))

    # Active Strategies
    active_strategies = Strategy.objects.filter(status='active')[:10]
    if active_strategies:
        elements.append(Paragraph("Active Strategies", styles['Heading2']))
        strat_data = [['Name', 'Horizon', 'P&L %', 'Max DD']]
        for st in active_strategies:
            strat_data.append([st.name[:30], st.time_horizon, f"{st.pnl_pct:+.2f}%", f"{st.max_drawdown:.2f}%"])
        t4 = Table(strat_data, colWidths=[2.5*inch, 1*inch, 1*inch, 1*inch])
        t4.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t4)

    # Footer
    elements.append(Spacer(1, 0.5*inch))
    elements.append(HRFlowable(width="100%", color=colors.grey))
    elements.append(Paragraph(f"Generated by Sauron Vision on {now.strftime('%Y-%m-%d %H:%M UTC')}",
                             ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="sauron_vision_report_{now.strftime("%Y%m%d")}.pdf"'
    return response
