import api
from datetime import datetime
import pytz

class TradeHistory:
    def __init__(self, baseURL, key, secret):
        self.client = api.Client(baseURL, key, secret)
    
    def format_trade_history(self, trades_data):
        """
        Format trade history data for display
        """
        if not trades_data or 'data' not in trades_data:
            return "❌ Нет данных о сделках"
        
        formatted_trades = []
        
        for trade in trades_data['data']:
            # Extract trade information
            market = trade.get('market', 'N/A')
            side = trade.get('side', 'N/A')
            amount = trade.get('amount', '0.00000000')
            price = trade.get('price', 'N/A')
            total = trade.get('total', 'N/A')
            executed_at = trade.get('executed_at', 'N/A')
            trade_id = trade.get('id', 'N/A')
            
            # Calculate total if not provided
            if price != 'N/A' and amount != '0.00000000':
                try:
                    calculated_total = float(price) * float(amount)
                    total = f"{calculated_total:.8f}"
                except (ValueError, TypeError):
                    pass
            
            # Format timestamp
            if executed_at != 'N/A':
                try:
                    timestamp = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                    local_time = timestamp.astimezone(pytz.timezone('Europe/Moscow'))
                    executed_at = local_time.strftime('%d.%m.%Y %H:%M')
                except:
                    executed_at = str(executed_at)
            
            # Determine status icon
            if amount == '0.00000000':
                status_icon = "❓"
            elif side == 'sell':
                status_icon = "❌"
            else:
                status_icon = "✅"
            
            # Format the trade entry
            trade_entry = f"{status_icon} {market}\n"
            trade_entry += f"   • Тип: {side.title()}\n"
            trade_entry += f"   • Количество: {amount}\n"
            trade_entry += f"   • Цена: {price}\n"
            trade_entry += f"   • Итого: {total} USDT\n"
            trade_entry += f"   • Время: {executed_at}\n"
            trade_entry += f"   • ID: {trade_id}..."
            
            formatted_trades.append(trade_entry)
        
        return "\n\n".join(formatted_trades)
    
    def get_trade_history(self, market=None, limit=50):
        """
        Get and format trade history
        """
        try:
            # Try to get completed trades first
            trades = self.client.get_trade_history(market=market, limit=limit)
            if trades and trades.get('data'):
                return self.format_trade_history(trades)
            
            # Fallback to completed orders if trades endpoint doesn't work
            orders = self.client.get_completed_orders(market=market, limit=limit)
            if orders and orders.get('data'):
                return self.format_trade_history(orders)
            
            return "❌ Не удалось получить историю сделок"
            
        except Exception as e:
            return f"❌ Ошибка при получении истории сделок: {str(e)}"
    
    def get_market_trades(self, market):
        """
        Get trades for a specific market
        """
        return self.get_trade_history(market=market)
