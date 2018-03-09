import etcd3
import json
import thread
from etcd3.events import PutEvent
from etcd3.events import DeleteEvent

JOB_PRIFIX = 'crms/job/'
WORKER_PREFIX = 'crms/worker/'
ASSIGN_PREFIX = 'crms/assign/'

class JobState(object):
  def __init__(self):
    self.status = 'new'
    self.stdouterr = ''

class Job(object):
  def __init__(self):
    self.id = ''
    self.command = [] # jobCommand is an array of each part of the command
    self.stateOfWorkers = {} # key: assigned worker name, value: JobData (state + stdout/err)

  def getStateOrCreateIfAbsent(self, workerName):
    if not self.stateOfWorkers.has_key(workerName):
      self.stateOfWorkers[workerName] = JobState()
    return self.stateOfWorkers[workerName]

class CrmsCli(object):
  def __init__(self):
    self.cli = etcd3.client()
    self.__workers = {} # key: worker name, value: worker parellel job count
    self.__cancelWatchWorkers = None
    self.__jobs = {} # key: jobId, value: Job
    self.__cancelWatchJobs = None

  def close(self):
    if self.__cancelWatchWorkers != None:
      self.__cancelWatchWorkers()
      self.__cancelWatchWorkers = None
    if self.__cancelWatchJobs != None:
      self.__cancelWatchJobs()
      self.__cancelWatchJobs = None

  def getWorkers(self):
    if self.__cancelWatchWorkers == None: # not watch yet
      self.__workers = self.__getWorkers()
      self.__watchWorkers()
    return self.__workers

  def __getWorkers(self):
    workers = self.cli.get_prefix(WORKER_PREFIX)
    return {wk[1].key : wk[0] for wk in workers}

  def __watchWorkers(self):
    evts, self.__cancelWatchWorkers = self.cli.watch_prefix(WORKER_PREFIX)
    def updateWorkers(evts):
      for evt in evts:
        if isinstance(evt, PutEvent):
          self.__workers[evt.key] = evt.value
        elif isinstance(evt, DeleteEvent):
          self.__workers.pop(evt.key)
    thread.start_new_thread(updateWorkers, (evts,))

  def stopWorker(self, name):
    self.cli.put(WORKER_PREFIX + name, 'close')

  def createJob(self, jobId, jobCommand): # jobCommand is an array of each part of the command
    cmd = json.dumps(jobCommand) # e.g: ['ls', '-l', '..']
    self.cli.put(JOB_PRIFIX + jobId, cmd)

  def runJob(self, jobId, workerNameList):
    for worker in workerNameList:
      self.cli.put(ASSIGN_PREFIX + worker + '/' + jobId, '')

  def __getJobOrCreateIfAbsent(self, jobId):
    if not self.__jobs.has_key(jobId):
      job = Job()
      job.id = jobId
      self.__jobs[jobId] = job
    return self.__jobs[jobId]

  def __updateJob(self, k, v):
    ks = k.split('/')
    n = len(ks)
    jobId = ks[1]
    job = self.__getJobOrCreateIfAbsent(jobId)
    if n == 2:
      job.id = jobId
      job.command = json.loads(v)
    elif n == 4:
      worker = ks[3]
      state = job.getStateOrCreateIfAbsent(worker)
      state.status = v
    elif n == 5:
      worker = ks[3]
      state = job.getStateOrCreateIfAbsent(worker)
      prop = ks[4]
      if prop == "stdouterr":
        state.stdouterr = v

  def __getJobs(self):
    ''' example of key-value format in etcd server:
    job/3
    ["ls", "-l", ".."]
    job/3/state/wenzhe
    done
    job/3/state/wenzhe/stdouterr
    total 1760
    drwxr-xr-x 1 weliu 1049089       0 Dec 13 17:18 angular
    drwxr-xr-x 1 weliu 1049089       0 Jan 17 16:53 bctools
    drwxr-xr-x 1 weliu 1049089       0 Jan  2 09:47 cluster
    '''
    jobs = self.cli.get_prefix(JOB_PRIFIX)
    for job in jobs:
      k = job[1].key
      v = job[0]
      self.__updateJob(k, v)
    return self.__jobs

  def __watchJobs(self):
    events, self.__cancelWatchJobs = self.cli.watch_prefix(JOB_PRIFIX)
    def updateJobs(evts):
      for evt in evts:
        if isinstance(evt, PutEvent):
          self.__updateJob(evt.key, evt.value)
        elif isinstance(evt, DeleteEvent):
          pass # currently no job remove yet
    thread.start_new_thread(updateJobs, (events,))

  def getJobs(self):
    if self.__cancelWatchJobs == None:
      self.__getJobs()
      self.__watchJobs()
    return self.__jobs

  def getJob(self, jobId):
    jobs = self.getJobs()
    return jobs[jobId]

  def getJobState(self, jobId, workerName):
    job = self.getJob(jobId)
    return job.stateOfWorkers[workerName]

# example of usage
if __name__ == "__main__":
  cli = CrmsCli()
  #import pdb
  #pdb.set_trace()
  print cli.getWorkers()
  import time
  #time.sleep(20)
  #print cli.getWorkers()
  cli.createJob("1234", ['pwd'])
  cli.runJob("1234", "wenzhe")
  def printJobs(jobs):
    for jobId, job in jobs.items():
      print "job id:", job.id
      print "job command", ' '.join(job.command)
      for worker, state in job.stateOfWorkers.items():
        print worker, state.status
        print state.stdouterr

  printJobs(cli.getJobs())
  cli.runJob("1234", "qiqi")
  printJobs(cli.getJobs())
  cli.close()
