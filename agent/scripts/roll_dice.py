import random

def roll_dice(sides=6):
    """Rolls a dice with the specified number of sides."""
    return random.randint(1, sides)

def main():
    print("You rolled a:", roll_dice())

if __name__ == "__main__":
    main()
