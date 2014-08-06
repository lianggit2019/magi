#!/usr/bin/env python

from magi.util import helpers
from pymongo import MongoClient
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import optparse
import os
import subprocess
import sys
import time


def create_tunnel(username, server, lport, rhost, rport):
    """
        Create a SSH tunnel and wait for it to be setup before returning.
        Return the SSH command that can be used to terminate the connection.
    """
    ssh_cmd = "ssh %s@%s -L %d:%s:%d -f -o ExitOnForwardFailure=yes -N" % (username,server, lport, rhost, rport)
    tun_proc = subprocess.Popen(ssh_cmd,
                                shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE)
    while True:
        p = tun_proc.poll()
        if p is not None: break
        time.sleep(1)
    
    if p != 0:
        raise RuntimeError, 'Error creating tunnel: ' + str(p) + ' :: ' + str(tun_proc.stdout.readlines())
    
    return ssh_cmd

if __name__ == '__main__':
 
    optparser = optparse.OptionParser(description="Plots the graph for an experiment based on parameters provided. \
													Experiment Configuration File OR Project and Experiment Name \
                                                    needs to be provided to be able to connect to the experiment.\
                                                    Need to provide build a graph specific configuration for plotting.")
                                                    
    optparser.add_option("-e", "--experiment", dest="experiment", help="Experiment name")
    optparser.add_option("-p", "--project", dest="project", help="Project name")
    optparser.add_option("-b", "--base", dest="base", help="Path and name of the experiment config file")
    optparser.add_option("-a", "--agent", dest="agent", help="Agent IDL in the experiment")
    optparser.add_option("-l", "--aal", dest="aal", help="AAL file of the experiment procedure")
    optparser.add_option("-T", "--Tunnel", dest="tunnel", default=False, help="Tunnel request through Deter Ops (users.deterlab.net).")
    optparser.add_option("-u", "--user", dest="user", help="Specific username to login into deter testbed")
    optparser.add_option("-c", "--config", dest="config", help="Path and name of configuration file for generating the graph")
    optparser.add_option("-o", "--output", dest="output", help="Path and name of output file for the graph") 
    (options, args) = optparser.parse_args()
    
    logging.basicConfig(format=helpers.LOG_FORMAT_MSECS,
                            datefmt=helpers.LOG_DATEFMT,
                            level=logging.INFO)
                            
    if options.agent:
        if options.aal:
            logging.info("Attempting to load the Agent IDL file")
            agentidl =  helpers.loadIDL(options.agent, options.aal)
            #logging.info(agentidl['dbfields'])
            logging.info("Displaying field names")
            print
            for field,desc in agentidl['dbfields'].items():
                print field, ':', desc
            print
            logging.info("Loaded IDL file")
        else:
            raise RuntimeError, 'Missing AAL file. Please provide AAL file with option -l'
            sys.exit(2)
    else:                            
     
        if options.config is None:
            optparser.print_help()
            sys.exit(2)
     
        if options.output is None:
            optparser.print_help()
            sys.exit(2)
    
        logging.info("Attempting to get the database config host from the experiment")
        dbConfigNode = helpers.getDBConfigHost(experimentConfigFile=options.base, project=options.project, experiment=options.experiment)
        #logging.info(dbConfigNode)
        logging.info("Got the database config host from the experiment")                                  
    
        logging.info("Attempting to load the Yaml file")
        config = helpers.loadYaml(options.config)
        logging.info("Loaded Yaml file")

        if not config.has_key('db') :
            raise RuntimeError, 'Configuration file incomplete. Database options are missing. Use option -a to get fields'
            sys.exit(2)
        else:
            if not config['db'].has_key('filter'):
                raise RuntimeError, 'Configuration file incomplete. Filter options are missing.Use option -a to get fields'
                sys.exit(2)
        
        #logging.info(config)
   
        try:
            tunnel_cmd = None		
            if options.tunnel:
                logging.info("Attempting to establish SSH tunnel")
                tunnel_cmd = create_tunnel(options.user,'users.deterlab.net',27018,\
	                       dbConfigNode, 27017)
                bridge = 'localhost'
                port = 27018
                logging.info('Tunnel setup done')
            else:
                bridge = dbConfigNode
                port = 27017
                #print bridge
                logging.info('Attempting to connect to the database')
        
            try:
                connection = MongoClient(bridge,port)
            except RuntimeError as e:
                logging.critical("Failed connecting to the database : %s", str(e))
                sys.exit(2)

            logging.info('Connected to the database')
            db = connection['magi']
            collection = db['experiment_data']
             
            x=[]
            y=[]
            config['db']['filter']['type'] = config['db']['collection']
            logging.info('The filter applied for data collected: %s',config['db']['filter'])	
            for firstvalue in collection.find(config['db']['filter']).sort("_id",1)[:1]:
                logging.info('The first timestamp in database: %s',firstvalue[config['db']['xValue']])

            logging.info('Fetching data from database')
            for post in collection.find(config['db']['filter']).sort("_id",1):
                #logging.info(firstvalue[config['db']['xValue']])
                #logging.info(post[config['db']['xValue']])
                x.append("%.8f" % (post[config['db']['xValue']] - firstvalue[config['db']['xValue']]))
                #y.append("%.3f" % ((post[config['db']['yValue']] * 8)/1000000.0))
                #logging.info((post[config['db']['yValue']] * 8)/1000000.0)
                y.append(post[config['db']['yValue']])
          
            logging.info('Constructed the x and y values for graph')
            #logging.info(x)
            #logging.info(y)
 
            logging.info('Preparing to plot values for graph')
            plt.xlabel(config['graph']['xLabel'])
            plt.ylabel(config['graph']['yLabel'])	
            plt.title(config['graph']['title'])
            ax = plt.subplot(111)
            ax.spines["right"].set_visible(False)
            ax.spines["top"].set_visible(False)
            ax.xaxis.set_ticks_position('bottom')
            ax.yaxis.set_ticks_position('left')
            lines = plt.plot(x, y)
            plt.setp(lines, 'color', 'r', 'linewidth', 2.0)
            plt.savefig(options.output)
            logging.info('Printed and saved the graph')	    

        finally:
            if tunnel_cmd:
                logging.info("Closing tunnel")
                os.system("kill -9 `ps -ef | grep '" + tunnel_cmd + "' | grep -v grep | awk '{print $2}'`")
