def summarize(values):
    """Return the count and sum, consuming the iterable once."""
    count = 0
    total = 0
    for value in values:
        count = count + 1
        total = total + value
    result = {}
    result['count'] = count
    result['total'] = total
    return result
