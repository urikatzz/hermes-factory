"""A list of validated trials retaining metadata even when the list is empty."""


class TrialSet(list):
    def __init__(self, trials, variants, synthetic, taskset_digest):
        super().__init__(trials)
        self.variants = variants
        self.synthetic = synthetic
        self.taskset_digest = taskset_digest
