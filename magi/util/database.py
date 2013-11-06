#!/usr/bin/env python

from subprocess import Popen
import logging
import os
import time
import errno
import ast
import itertools

from magi.util import config
from magi.testbed import testbed

import pymongo
from pymongo import MongoClient

log = logging.getLogger(__name__)

def startDBServer(configfile=None):
    
    try:
        log.info("Checking if an instance of mongod server is already running")
        if isDBRunning():
            return

        if configfile is None:
            configfile = createMongoDConfig()

        try:
            os.makedirs('/var/lib/mongodb')  # Make sure mongodb data directory is around
        except OSError, e:
            if e.errno != errno.EEXIST:
                log.error("failed to created mondodb data dir: %s", e, exc_info=1)
                raise

        try:
            os.makedirs('/var/log/mongodb')  # Make sure mongodb log directory is around
        except OSError, e:
            if e.errno != errno.EEXIST:
                log.error("failed to created mondodb log dir: %s", e, exc_info=1)
                raise

        log.info("Starting mongod")
        while True:
            mongod = ['/usr/local/bin/mongod', '--config', configfile, '--journal']
            p = Popen(mongod)
            time.sleep(1)
            if p.poll() is None:
                break
            log.error("Failed to start mongod server")
        
        pid = p.pid
        log.info("Started mongod with pid %s", pid)
    
    except Exception, e:
        log.error("Exception while setting up mongo db database server: %s", e)
        raise

def createMongoDConfig():
    try:
        log.info("Creating mongo db config file.....")
        configfile = '/tmp/mongod.conf'
        f = open(configfile, 'w')
        f.write('dbpath=/var/lib/mongodb\n')
        f.write('logpath=/var/log/mongodb/mongodb.log\n')
        f.write('logappend=true\n')
        f.close() 
    except Exception, e:
        log.error("Failed to create mongodb default configuration file: %s", e)
        raise
    return configfile

def getCollection(collectionname, dbhost=None):
    global collectionHosts
    if dbhost == None:
        dbhost = getDBHost()
    try:
        if collectionHosts[collectionname] != dbhost:
            log.error("Multiple db hosts for same collection")
            raise Exception("Multiple db hosts for same collection")
    except KeyError:
        collectionHosts[collectionname] = dbhost
    return Collection(collectionname, dbhost)

def getData(collectionname, filters=None, timestampRange=None, connection=None):
    functionName = getData.__name__
    entrylog(functionName, locals())
        
    if not isDBHost:
        return None

    if connection == None:
        connection = getConnection('localhost')
            
    if filters == None:
        filters_copy = dict()
    else:
        filters_copy = filters.copy()
        
    if timestampRange:
        ts_start, ts_end = timestampRange
        filters_copy['created'] = {'$gte': ts_start, '$lte': ts_end}
        
    cursor = connection[dbname][collectionname].find(filters_copy)
    
    result = []
    
    while True:
        try:
            result.append(cursor.next())
        except StopIteration:
            break
    
    exitlog(functionName, result)
    return result

def updateDatabase(collectionname, filters=None, timestampChunks=None, data=[], connection=None):
    functionName = updateDatabase.__name__
    entrylog(functionName, locals())
    
    if not isDBHost:
        return
        
    if connection == None:
        connection = getConnection('localhost')
                
    collection = connection[dbname][collectionname]
        
    for record in data:
        try:
            collection.insert(record)
        except StopIteration:
            break
        except:
            continue
        
    updateMetadata(collectionname, filters, timestampChunks, connection)
    
    exitlog(functionName)

def updateMetadata(collectionname, filters=None, timestampChunks=None, connection=None): 
    functionName = updateMetadata.__name__
    entrylog(functionName, locals())
    
    if not timestampChunks:
        return
    
    if not isDBHost:
        return
        
    if filters == None:
        filters = dict()
        
    if connection == None:
        connection = getConnection('localhost')
                
    itr = connection['cache']['metadata'].find({'db': dbname, 'collection': collectionname})        
    while True:
        try:
            record = itr.next()
            rec_filters = ast.literal_eval(record['filters'])
            
            #if filters == {k: rec_filters[k] for k in filters.keys() if k in rec_filters}:
            sub_rec_filters = dict()
            for k in filters.keys():
                if k in rec_filters:
                    sub_rec_filters[k] = rec_filters[k]
                    
            if filters == sub_rec_filters:
                ts_chunks = record['ts_chunks']
                ts_chunks = insertChunks(ts_chunks, timestampChunks)
                connection['cache']['metadata'].update({'_id': record['_id'] }, { '$set': { 'ts_chunks': ts_chunks } })                        

        except StopIteration:
            break

    itr = connection['cache']['metadata'].find({'db': dbname, 'collection': collectionname, 'filters': str(filters)})
    try:
        record = itr.next()
    except StopIteration:
        record = {"db": dbname, "collection": collectionname, 'filters': str(filters), 'ts_chunks': timestampChunks}
        log.debug("cache.metadata insertion: " + str(record))
        connection['cache']['metadata'].insert(record)
                
    exitlog(functionName)

def findTimeRangeNotAvailable(collectionname, filters=None, timestampRange=None, connection=None):
    functionName = findTimeRangeNotAvailable.__name__
    entrylog(functionName, locals())
    
    if timestampRange == None:
        timestampRange = (0, time.time())
        
    if not isDBHost:
        return [timestampRange]

    availableTimeRange = getAvailableTimeRange(collectionname, filters, connection)
    missingTimeRange = findMissingTimeRange(availableTimeRange, timestampRange)

    exitlog(functionName, missingTimeRange)
    return missingTimeRange


def getAvailableTimeRange(collectionname, filters=None, connection=None):
    functionName = getAvailableTimeRange.__name__
    entrylog(functionName, locals())
    
    if not isDBHost:
        return []
            
    if filters == None:
        filters = dict()
        
    result = []
            
    filterKeys = filters.keys()
    
    for subsetLength in range(len(filterKeys)+1):
        filterKeysSubsets = itertools.combinations(filterKeys, subsetLength)
        for filterKeysSubset in filterKeysSubsets:
            #subsetFilters = {k: filters[k] for k in filterKeysSubset}
            subsetFilters = dict()
            for k in filterKeysSubset:
                subsetFilters[k] = filters[k]
            availableTimeRange = getAvailableTimeRangeForExactFilter(collectionname, subsetFilters, connection)
            result = insertChunks(result, availableTimeRange)
            
    exitlog(functionName)
    return result
        
def getAvailableTimeRangeForExactFilter(collectionname, filters=None, connection=None):
    functionName = getAvailableTimeRangeForExactFilter.__name__
    entrylog(functionName, locals())
    
    if not isDBHost:
        return []
    
    if filters == None:
        filters = dict()
    
    if connection == None:
        connection = getConnection('localhost')
    
    itr = connection['cache']['metadata'].find({'db': dbname, 'collection': collectionname})
    
    while True:
        try:
            record = itr.next()
            log.debug(record)
            rec_filters = ast.literal_eval(record['filters'])
            if filters == rec_filters:
                result = record['ts_chunks']
                break
        except StopIteration:
                result = []
                break
            
    exitlog(functionName)
    return result

def findMissingTimeRange(availableTimeRange, requiredTimeRange):
    functionName = findMissingTimeRange.__name__
    entrylog(functionName)
            
    if availableTimeRange == None:
        return [requiredTimeRange]
        
    chunksNotAvailable = []
    reqdStart, reqdEnd = requiredTimeRange

    availableTimeRange.sort(reverse=True)

    for chunkStart, chunkEnd in availableTimeRange:
                
        if reqdStart > chunkEnd:
            chunksNotAvailable = chunksNotAvailable + [(reqdStart, reqdEnd)]
            exitlog(functionName, chunksNotAvailable)
            return chunksNotAvailable
                            
        if reqdEnd > chunkEnd:
            chunksNotAvailable = chunksNotAvailable + [(chunkEnd, reqdEnd)]
                                
        if reqdStart >= chunkStart:
            exitlog(functionName, chunksNotAvailable)
            return chunksNotAvailable
                                    
        if reqdEnd > chunkStart:
            reqdEnd = chunkStart

    chunksNotAvailable = chunksNotAvailable + [(reqdStart, reqdEnd)]

    exitlog(functionName)
    return chunksNotAvailable

def insertChunks(existingChunks, newChunks):
        functionName = insertChunks.__name__
        entrylog(functionName)
    
        if not newChunks:
            return existingChunks
        
        if not existingChunks:
            return newChunks
        
        existingChunks.sort(reverse=True)
        newChunks.sort(reverse=True)
        
        result = existingChunks[:]
        ptr = 0
        
        for newChunk in newChunks:
            
            newStart, newEnd = newChunk
            
            while ptr < len(result):
                chunk = result[ptr]
                chunkStart, chunkEnd = chunk
                
                if newStart > chunkEnd:
                    break

                elif newEnd < chunkStart:
                    ptr += 1
                
                else:
                    if newEnd < chunkEnd:
                        newEnd = chunkEnd
                    if newStart > chunkStart:
                        newStart = chunkStart
                    result.remove(chunk)
                
            result.insert(ptr, (newStart, newEnd))
            
        exitlog(functionName)
        return result

    
def getConnection(dbhost=None, block=True):
    global connectionMap
    
    if dbhost == None:
        dbhost = getDBHost()
    while True:
        try:
            log.debug("Trying to connect to database server")
            if dbhost not in connectionMap:
                connection = MongoClient(dbhost, 27017)
                connectionMap[dbhost] = connection
            log.debug("Connected to database server")
            return connectionMap[dbhost]
        except Exception:
            log.error("Could not connect to database server")
            if not block:
                raise
            time.sleep(1)

def getDBHost():
    return dbhost

def isDBRunning():
    try:        
        getConnection('localhost', False)
        log.info("An instance of database server is already running")
        return True
    except pymongo.errors.ConnectionFailure:
        log.info("No instance of database server is already running")
        return False
        
def entrylog(functionName, arguments=None):
    if arguments == None:
        log.debug("Entering function %s", functionName)
    else:
        log.debug("Entering function %s with arguments: %s", functionName, arguments)

def exitlog(functionName, returnValue=None):
    if returnValue == None:
        log.debug("Exiting function %s", functionName)
    else:
        log.debug("Exiting function %s with return value: %s", functionName, returnValue)


dbname = 'magi'
configData = config.getConfig()
dbhost = configData.get('dbhost')
isDBHost = configData.get('isDBHost')

if 'connectionMap' not in locals():
    connectionMap = dict()
if 'collectionHosts' not in locals():
    collectionHosts = dict()
    collectionHosts['log'] = getDBHost()


class Collection():
    """Library to use for data collection"""

    def __init__(self, collectionname, dbhost=None):
        if dbhost == None:
            dbhost = getDBHost()
        connection = getConnection(dbhost)
        self.collection = connection[dbname][collectionname]

    def insert(self, **kwargs):
        kwargs['host'] = testbed.nodename
        kwargs['created'] = time.time()
        self.collection.insert(kwargs)
        
    def remove(self):
        self.collection.remove()


#def insertChunk(existingChunks=[], newChunk=None):
#        
#        if newChunk == None:
#                return existingChunks
#        
#        existingChunks.sort()
#        
#        result = existingChunks[:]
#                
#        newStart, newEnd = newChunk
#        
#        for chunk in existingChunks:
#                chunkStart, chunkEnd = chunk
#                
#                if newEnd < chunkStart:
#                        result.insert(result.index(chunk), (newStart, newEnd))
#                        return result
#                
#                if newStart <= chunkEnd:
#                        if newStart > chunkStart:
#                                newStart = chunkStart
#                        if newEnd < chunkEnd:
#                                newEnd = chunkEnd
#                        result.remove(chunk)
#        
#        result.append((newStart, newEnd))
#        return result
     
#def findMissingChunks(availableChunks, requiredChunk):
#        
#        if availableChunks == None:
#                return [requiredChunk]
#        
#        chunksNotAvailable = []
#        reqdStart, reqdEnd = requiredChunk
#
#        availableChunks.sort()
#        
#        for chunkStart, chunkEnd in availableChunks:
#                
#                if reqdEnd < chunkStart:
#                        chunksNotAvailable = chunksNotAvailable + [(reqdStart, reqdEnd)]
#                        return chunksNotAvailable
#                            
#                if reqdStart < chunkStart:
#                        chunksNotAvailable = chunksNotAvailable + [(reqdStart, chunkStart)]
#                                
#                if reqdEnd <= chunkEnd:
#                        return chunksNotAvailable
#                                    
#                if reqdStart < chunkEnd:
#                        reqdStart = chunkEnd
#
#        chunksNotAvailable = chunksNotAvailable + [(reqdStart, reqdEnd)]
#
#        return chunksNotAvailable