import crmscli
import random
import time
import os.path
import logging
import sys
import threading
from datetime import datetime

LOG_PATH = "~/.gocrms/performance.log"

class CountDownLatch(object):
    def __init__(self, count=1):
        self.count = count
        self.lock = threading.Condition()

    def count_down(self):
        self.lock.acquire()
        self.count -= 1
        if self.count <= 0:
            self.lock.notifyAll()
        self.lock.release()

    def await(self):
        self.lock.acquire()
        while self.count > 0:
            self.lock.wait()
        self.lock.release()


class JobTime(object):
    def __init__(self):
        self.start_on_client = None
        self.start_on_worker = None
        self.end_on_worker = None
        self.end_on_client = None
        self.worker = ""

    def start_cost(self):
        return self.start_on_worker - self.start_on_client

    def end_cost(self):
        return self.end_on_client - self.end_on_worker

class Summary(object):
    def __init__(self):
        self.workers = []
        self.start_time = datetime.now()
        self.jobs_time = {}

    def get_job(self, job_id):
        if self.jobs_time.has_key(job_id):
            return self.jobs_time[job_id]
        else:
            jt = JobTime()
            self.jobs_time[job_id] = jt
            return jt

    def parse_worker_log(self, worker):
        '''
        the worker's log format is like this:
        2018/03/23 11:42:44.374266 worker.go:150: Run Job 1 with command: python -c print 1
        2018/03/23 11:42:45.005266 worker.go:156: Finish Job 0 with result:  0
        '''
        RUN_JOB = 'Run Job '
        LEN_RUN = len(RUN_JOB)
        FINISH_JOB = 'Finish Job '
        LEN_FINISH = len(FINISH_JOB)

        logfile = os.path.expanduser('~/.gocrms/%s.log' % worker)
        with open(logfile) as f:
            for line in f:
                tags = line.split(' ', 4)
                dt = datetime.strptime(' '.join(tags[:2]), '%Y/%m/%d %H:%M:%S.%f')
                if dt <= self.start_time:
                    continue
                content = tags[3]
                if content.startswith(RUN_JOB):
                    job_id = self.find_job_id(content[LEN_RUN:])
                    self.get_job(job_id).worker = worker
                    self.get_job(job_id).start_on_worker = dt
                elif content.startswith(FINISH_JOB):
                    job_id = self.find_job_id(content[LEN_FINISH:])
                    self.get_job(job_id).worker = worker
                    self.get_job(job_id).end_on_worker = dt

    def parse_client_log(self):
        '''
        log format:
        2018-03-23 10:13:37,927 run job 1 on worker w1
        2018-03-23 10:13:38,269 finish job 0 with result 0
        '''
        RUN_JOB = 'run job '
        LEN_RUN = len(RUN_JOB)
        FINISH_JOB = 'finish job '
        LEN_FINISH = len(FINISH_JOB)

        logfile = os.path.expanduser(LOG_PATH)
        with open(logfile) as f:
            for line in f:
                tags = line.split(' ', 3)
                dt = datetime.strptime(' '.join(tags[:2]), '%Y-%m-%d %H:%M:%S,%f')
                if dt <= self.start_time:
                    continue
                content = tags[2]
                if content.startswith(RUN_JOB):
                    job_id = self.find_job_id(content[LEN_RUN:])
                    self.get_job(job_id).start_on_client = dt
                elif content.startswith(FINISH_JOB):
                    job_id = self.find_job_id(content[LEN_FINISH:])
                    self.get_job(job_id).end_on_client = dt

    @staticmethod
    def find_job_id(s):
        i = s.find(' ')
        if i == -1:
            return s
        else:
            return s[:i]

    def parse_log(self):
        self.parse_client_log()
        for worker in summary.workers:
            self.parse_worker_log(worker)

    def average_start_cost(self):
        start_costs = [jt.start_cost for jt in self.jobs_time.values()]
        # TODO


    def report(self):
        fmt = '%-7s | %-7s | %-7s | %-7s | %-15s | %-15s | %-15s | %-15s'
        print fmt % (
            'job id', 'worker', 'st cost', 'endcost',
            'start on client', 'start on worker', 'end on worker', 'end on client'
        )
        for job_id, jt in sorted(self.jobs_time.items()):
            print fmt % (
                job_id, jt.worker, jt.start_cost(), jt.end_cost(),
                jt.start_on_client, jt.start_on_worker, jt.end_on_worker, jt.end_on_client
            )
        print 'average start cost:', self.average_start_cost()


logger = logging.getLogger("crms")
jobcount = 2
jobs_finished_count = CountDownLatch(jobcount)
summary = Summary()


def on_job_status_changed(job):
    job_state = job.get_state()
    # print "job", job.id, "status change to", job_state.status
    if job_state.status in ['done', 'fail']:
        logger.info('finish job %s with result %s', job.id, job_state.stdouterr)
        jobs_finished_count.count_down()


def test_run_job(job_count):
    with crmscli.CrmsCli() as crms:
        crms.add_watcher(on_job_status_changed)

        crms.clean()

        workers = crms.get_workers().keys()
        print "workers:", workers
        if len(workers) == 0:
            return
        summary.workers = workers
        for i in xrange(job_count):
            f = os.path.join(os.path.dirname(__file__), 'mock_job.py')
            job_id = str(i)
            logger.info('create job %s', job_id)
            crms.create_job(job_id, ['python', '-c', 'print ' + job_id])
            worker = random.choice(workers)
            logger.info('run job %s on worker %s', job_id, worker)
            crms.run_job(job_id, worker)

        jobs_finished_count.await()
        print_nodes(crms.nodes())


def print_nodes(nodes):
    print("nodes:")
    for (k, v) in sorted(nodes.items()):
        print k, ":", v


def init_log():
    formatter = logging.Formatter('%(asctime)s %(message)s', )
    logfile = os.path.expanduser(LOG_PATH)
    file_handler = logging.FileHandler(logfile)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)


if __name__ == "__main__":
    init_log()
    test_run_job(jobcount)
    summary.parse_log()
    summary.report()