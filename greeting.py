import time
import statistics

def say_hello():
    print("Hello")

def calculate_statistics(execution_times):
    mean_execution_time = statistics.mean(execution_times)
    median_execution_time = statistics.median(execution_times)
    std_dev_execution_time = statistics.stdev(execution_times)
    return mean_execution_time, median_execution_time, std_dev_execution_time

def format_statistics(mean, median, std_dev):
    return f"""
    Statistical Metrics:
    -------------------
    Mean Execution Time: {mean:.6f} seconds
    Median Execution Time: {median:.6f} seconds
    Standard Deviation of Execution Time: {std_dev:.6f} seconds
    """

def main():
    execution_times = []
    for _ in range(1000):
        start_time = time.time()
        say_hello()
        end_time = time.time()
        execution_times.append(end_time - start_time)

    mean_execution_time, median_execution_time, std_dev_execution_time = calculate_statistics(execution_times)
    print(format_statistics(mean_execution_time, median_execution_time, std_dev_execution_time))

if __name__ == "__main__":
    main()
