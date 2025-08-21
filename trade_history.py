import api
from datetime import datetime
import pytz
import logging

class TradeHistory:
    def __init__(self, baseURL, key, secret):
        self.client = api.Client(baseURL, key, secret)
        logging.info("TradeHistory client initialized with cloudscraper support")
    
    def format_trade_history(self, trades_data):
        """
        Format trade history data for display with enhanced data processing
        """
        if not trades_data:
            return "❌ Нет данных о сделках"
        
        # Handle different data structures from SafeTrade API
        trades = []
        if isinstance(trades_data, dict):
            if 'data' in trades_data:
                trades = trades_data['data']
            elif 'trades' in trades_data:
                trades = trades_data['trades']
            elif 'orders' in trades_data:
                trades = trades_data['orders']
            else:
                # If it's a single trade object
                trades = [trades_data]
        elif isinstance(trades_data, list):
            trades = trades_data
        else:
            return "❌ Неожиданная структура данных о сделках"
        
        if not trades:
            return "❌ Нет данных о сделках"
        
        formatted_trades = []
        
        for trade in trades:
            try:
                # Extract trade information with SafeTrade API field mapping
                market = trade.get('market', trade.get('symbol', 'N/A'))
                side = trade.get('side', trade.get('type', 'N/A'))
                
                # SafeTrade uses filled_amount for executed amount, origin_amount for original
                amount = trade.get('filled_amount', trade.get('amount', trade.get('volume', '0.00000000')))
                
                # SafeTrade uses avg_price for executed price, price for limit price
                price = trade.get('avg_price', trade.get('price', trade.get('executed_price', 'N/A')))
                
                # For SafeTrade, we usually need to calculate total from avg_price * filled_amount
                total = trade.get('total', trade.get('executed_volume', 'N/A'))
                
                # SafeTrade uses triggered_at for execution time, created_at for order creation
                executed_at = trade.get('triggered_at', trade.get('executed_at', trade.get('created_at', trade.get('timestamp', 'N/A'))))
                trade_id = trade.get('id', trade.get('trade_id', 'N/A'))
                
                # Convert amount to float for calculations
                try:
                    amount_float = float(amount) if amount != 'N/A' else 0
                except (ValueError, TypeError):
                    amount_float = 0
                
                # Calculate total if not provided or if it's 0
                # SafeTrade often doesn't provide total, so we calculate it from avg_price * filled_amount
                if (price != 'N/A' and amount_float > 0 and 
                    (total == 'N/A' or total == 0 or total == '0.00000000' or str(total) == '0')):
                    try:
                        price_float = float(price)
                        calculated_total = price_float * amount_float
                        total = f"{calculated_total:.8f}"
                        logging.debug(f"Calculated total for {market}: {price_float} * {amount_float} = {calculated_total}")
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Could not calculate total for {market}: {e}")
                        total = 'N/A'
                
                # If we still have total as a string number, convert it to proper format
                if total != 'N/A':
                    try:
                        total_float = float(total)
                        total = f"{total_float:.8f}"
                    except (ValueError, TypeError):
                        pass
                
                # Format timestamp
                if executed_at != 'N/A':
                    try:
                        # Handle different timestamp formats
                        if isinstance(executed_at, str):
                            if 'T' in executed_at:
                                # ISO format
                                timestamp = datetime.fromisoformat(executed_at.replace('Z', '+00:00'))
                            else:
                                # Unix timestamp
                                timestamp = datetime.fromtimestamp(float(executed_at))
                        else:
                            # Assume it's already a datetime object
                            timestamp = executed_at
                        
                        local_time = timestamp.astimezone(pytz.timezone('Europe/Moscow'))
                        executed_at = local_time.strftime('%d.%m.%Y %H:%M')
                    except Exception as e:
                        logging.warning(f"Could not parse timestamp {executed_at}: {e}")
                        executed_at = str(executed_at)
                
                # Determine status icon based on trade state and side
                trade_state = trade.get('state', 'unknown').lower()
                if trade_state == 'done' and amount_float > 0:
                    # Completed trade
                    if side.lower() == 'sell':
                        status_icon = "❌"  # Red for sell
                    elif side.lower() == 'buy':
                        status_icon = "✅"  # Green for buy
                    else:
                        status_icon = "✅"  # Default green for completed
                elif trade_state in ['cancelled', 'cancel']:
                    status_icon = "⚠️"  # Warning for cancelled
                elif amount_float == 0 or trade_state in ['wait', 'pending']:
                    status_icon = "❓"  # Question for pending/zero amount
                else:
                    status_icon = "❓"  # Default question mark
                
                # Format the trade entry
                trade_entry = f"{status_icon} {market.upper()}\n"
                trade_entry += f"   • Тип: {side.title()}\n"
                trade_entry += f"   • Количество: {amount}\n"
                trade_entry += f"   • Цена: {price}\n"
                trade_entry += f"   • Итого: {total} USDT\n"
                trade_entry += f"   • Время: {executed_at}\n"
                trade_entry += f"   • ID: {trade_id}..."
                
                formatted_trades.append(trade_entry)
                
            except Exception as e:
                logging.error(f"Error formatting trade entry: {e}")
                logging.error(f"Problematic trade data: {trade}")
                continue
        
        if not formatted_trades:
            return "❌ Не удалось отформатировать данные о сделках"
        
        return "\n\n".join(formatted_trades)
    
    def get_trade_history(self, market=None, limit=50):
        """
        Get and format trade history with enhanced endpoint handling
        """
        try:
            logging.info(f"Fetching trade history for market: {market}, limit: {limit}")
            
            # Try multiple endpoints to get the best data
            trades = None
            
            # First, try the dedicated trades endpoint
            try:
                trades = self.client.get_trade_history(market=market, limit=limit)
                if trades and trades.get('data'):
                    logging.info(f"Successfully got {len(trades['data'])} trades from trades endpoint")
                    return self.format_trade_history(trades)
            except Exception as e:
                logging.warning(f"Trades endpoint failed: {e}")
            
            # Fallback to completed orders
            try:
                orders = self.client.get_completed_orders(market=market, limit=limit)
                if orders and orders.get('data'):
                    logging.info(f"Successfully got {len(orders['data'])} completed orders")
                    return self.format_trade_history(orders)
            except Exception as e:
                logging.warning(f"Completed orders endpoint failed: {e}")
            
            # Try general orders endpoint
            try:
                all_orders = self.client.get_orders()
                if all_orders and all_orders.get('data'):
                    # Filter for completed orders
                    completed_orders = [order for order in all_orders['data'] 
                                     if order.get('state') in ['done', 'filled', 'completed']]
                    if completed_orders:
                        logging.info(f"Found {len(completed_orders)} completed orders from general endpoint")
                        return self.format_trade_history({'data': completed_orders})
            except Exception as e:
                logging.warning(f"General orders endpoint failed: {e}")
            
            return "❌ Не удалось получить историю сделок ни с одного эндпоинта"
            
        except Exception as e:
            logging.error(f"Error getting trade history: {e}")
            return f"❌ Ошибка при получении истории сделок: {str(e)}"
    
    def get_market_trades(self, market):
        """
        Get trades for a specific market
        """
        return self.get_trade_history(market=market)
    
    def get_recent_trades(self, limit=10):
        """
        Get recent trades with enhanced data processing
        """
        try:
            # Try to get the most recent trades
            trades = self.client.get_trade_history(limit=limit)
            if trades and trades.get('data'):
                # Sort by timestamp if available
                data = trades['data']
                try:
                    data.sort(key=lambda x: x.get('executed_at', x.get('created_at', '0')), reverse=True)
                except:
                    pass  # If sorting fails, use original order
                return self.format_trade_history({'data': data[:limit]})
            else:
                return "❌ Нет данных о последних сделках"
        except Exception as e:
            logging.error(f"Error getting recent trades: {e}")
            return f"❌ Ошибка при получении последних сделок: {str(e)}"
