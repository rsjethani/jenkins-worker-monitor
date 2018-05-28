#!/usr/bin/python3


import os
import math
import docker
import jenkins
import shutil
import time
import logging
import signal


##### GET required values from Environment variables #####
try:
    JENKINS_USER = os.environ["JENKINS_USER"]
    JENKINS_PASS = os.environ["JENKINS_PASS"]
    JENKINS_NODE = os.environ["JENKINS_NODE"]
    DISK_THRESHOLD = int(os.getenv("DISK_THRESHOLD", "70"))
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
except KeyError as e:
    raise SystemExit("environment variable {} not found".format(e))
except ValueError as e:
    raise SystemExit("Error: Not an integer: ".format(e.args[0].split(":")[-1]))

JENKINS_URL = os.getenv("JENKINS_URL", "https://engci-private-sjc.cisco.com/jenkins/iotsp/")
DOCKER_HOST_URL = os.getenv("DOCKER_HOST_URL", "unix://docker.sock")
DOCKER_ROOT_DIR = os.getenv("DOCKER_ROOT_DIR", "/docker")
DOCKER_KEEP_IMAGES_UNTIL = os.getenv("DOCKER_KEEP_IMAGES_UNTIL", "72"
DOCKER_API_VERSION = os.getenv("DOCKER_API_VERSION", "1.30")
WORKSPACE_ROOT_DIR = os.getenv("WORKSPACE_ROOT_DIR", "/workspace")


##### Configure logging #####
logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(funcName)s : %(message)s")

##### Configure handling of Ctrl+C(SIGINT) , docker stop(SIGTERM) signals #####
def signal_handler(sigid, frame):
    log.warning("SIGINT/SIGTERM signal received")
    if STAGE >= 1:
        log.warning("signal received during cleanup, aborting cleanup and putting node back online, the cleanup may not have completed properly")
        make_node_online()
    raise SystemExit(sigid)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def make_node_online():
    logging.info("trying to put node '{}' back online".format(JENKINS_NODE))
    server = jenkins.Jenkins(JENKINS_URL, username=JENKINS_USER, password=JENKINS_PASS)
    server.get_version()
    server.enable_node(JENKINS_NODE)
    logging.info("node '{}' is now online".format(JENKINS_NODE))
    return True


def make_node_offline():
    logging.info("checking node '{}' status".format(JENKINS_NODE))
    server = jenkins.Jenkins(JENKINS_URL, username=JENKINS_USER, password=JENKINS_PASS)
    server.get_version()
    node_idle = server.get_node_info(JENKINS_NODE)["idle"]
    if node_idle:
        logging.info("node '{}' is currently idle, trying to put it offline".format(JENKINS_NODE))
        server.disable_node(JENKINS_NODE, msg="jenkins-worker-monitor: putting offline for cleanup")
        logging.info("node '{}' is now offline".format(JENKINS_NODE))
        return True
    else:
        logging.warning("node '{}' is currently not idle, cannot put it offline".format(JENKINS_NODE))
        return False


def cleanup_docker():
    logging.info("starting docker cleanup")
    docker_client = docker.DockerClient(base_url=DOCKER_HOST_URL, version=DOCKER_API_VERSION)

    byts = docker_client.containers.prune()["SpaceReclaimed"]
    logging.info("cleaned up stopped/stale containers, space reclaimed: {} bytes".format(byts))

    byts = docker_client.volumes.prune()["SpaceReclaimed"]
    logging.info("cleaned up unused/dangling volumes, space reclaimed: {} bytes".format(byts))

    byts = docker_client.images.prune(filters={"dangling": False, "until": DOCKER_KEEP_IMAGES_UNTIL + "h"})["SpaceReclaimed"]
    logging.info("cleaned up all dangling images and unused images(older than {} hours), space reclaimed: {} bytes".format(until, byts))

    logging.info("finished docker cleanup")


def cleanup_workspace():
    logging.info("starting workspace cleanup at '{}'".format(WORKSPACE_ROOT_DIR))
    shutil.rmtree(WORKSPACE_ROOT_DIR, ignore_errors=True)
    os.makedirs(WORKSPACE_ROOT_DIR, exist_ok=True)
    logging.info("finished workspace cleanup")


def check_disk_usage(path):
    total, used, available = shutil.disk_usage(path)
    used_perc = math.ceil(used / total * 100)

    critical = used_perc >= DISK_THRESHOLD
    if critical:
        logging.critical("disk usage of {}: ~{}% [DISK_THRESHOLD: {}%]".format(path, used_perc, DISK_THRESHOLD))
    else:
        logging.info("disk usage of {}: ~{}% [DISK_THRESHOLD: {}%]".format(path, used_perc, DISK_THRESHOLD))

    return critical
    
STAGE = 0

def main():
    while True:
        STAGE = 0
        logging.info("***** checking disk usage *****")

        try:
            docker_usage_critical = check_disk_usage(DOCKER_ROOT_DIR)
            workspace_usage_critical = check_disk_usage(WORKSPACE_ROOT_DIR)
            
            node_offline = False
            if docker_usage_critical or workspace_usage_critical:
                logging.info("starting cleanup operations")
                node_offline = make_node_offline()

                if node_offline:
                    STAGE = 1
                    if docker_usage_critical:
                        cleanup_docker()
                    if workspace_usage_critical:
                        cleanup_workspace()

                    logging.info("disk usage after cleanup:")
                    check_disk_usage(DOCKER_ROOT_DIR)
                    check_disk_usage(WORKSPACE_ROOT_DIR)
                    logging.info("finished all cleanup operations")
                else:
                    logging.warning("skipping cleanup")

        except Exception as e:
            logging.error(e)
        finally:
            if node_offline:
                make_node_online()
                STAGE = 0

        logging.info("***** checking again after {} minute(s) *****".format(CHECK_INTERVAL))
        time.sleep(CHECK_INTERVAL * 60)


if __name__ == "__main__":
    main()

