"""
Test the floor rounding fix for NOCK
"""
import math

def test_floor_rounding():
    """Test that floor rounding works correctly"""
    
    # Original balance from logs
    balance = 177.83966849
    precision = 4
    
    # OLD METHOD (standard rounding - WRONG!)
    old_formatted = f"{balance:.{precision}f}"
    old_rounded = float(old_formatted)
    
    # NEW METHOD (floor rounding - CORRECT!)
    new_rounded = math.floor(balance * 10**precision) / 10**precision
    
    print("=" * 60)
    print("ТЕСТ ОКРУГЛЕНИЯ")
    print("=" * 60)
    print(f"Баланс:               {balance}")
    print(f"Точность:             {precision} знаков")
    print()
    print(f"❌ СТАРЫЙ метод:       {old_rounded}")
    print(f"   Проблема:          {old_rounded} > {balance} = {old_rounded > balance}")
    print()
    print(f"✅ НОВЫЙ метод:        {new_rounded}")
    print(f"   Безопасно:         {new_rounded} <= {balance} = {new_rounded <= balance}")
    print()
    print(f"Разница:              {old_rounded - new_rounded}")
    print("=" * 60)
    
    # Verify new method never exceeds balance
    assert new_rounded <= balance, "Floor rounding should never exceed balance"
    assert new_rounded == 177.8396, f"Expected 177.8396, got {new_rounded}"
    
    print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    print(f"Новый метод округляет {balance} → {new_rounded}")
    print(f"Это БЕЗОПАСНО для продажи (не превышает баланс)")

if __name__ == "__main__":
    test_floor_rounding()
