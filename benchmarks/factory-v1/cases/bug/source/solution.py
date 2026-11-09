def in_range(values, lower, upper):
    """Return values between lower and upper, including both bounds."""
    return [value for value in values if lower <= value < upper]
