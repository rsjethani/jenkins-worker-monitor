#!/usr/bin/python3


import os
import math
import docker
import jenkins
import shutil
import time
import logging


try:
    JENKINS_USER = os.environ["JENKINS_USER"]
    JENKINS_PASS = os.environ["JENKINS_PASS"]
    JENKINS_NODE = os.environ["JENKINS_NODE"]
except KeyError as e:
    raise SystemExit("environment variable {} not found".format(e))


JENKINS_URL = os.getenv("JENKINS_URL", "https://engci-private-sjc.cisco.com/jenkins/iotsp/")
DISK_THRESHOLD = int(os.getenv("DISK_THRESHOLD", "70"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
DOCKER_HOST_URL = os.getenv("DOCKER_HOST_URL", "unix://docker.sock")
DOCKER_ROOT_DIR = os.getenv("DOCKER_ROOT_DIR", "/docker")
DOCKER_KEEP_IMAGES_UNTIL = os.getenv("DOCKER_KEEP_IMAGES_UNTIL", "72"
DOCKER_API_VERSION = os.getenv("DOCKER_API_VERSION", "1.30")
WORKSPACE_ROOT_DIR = os.getenv("WORKSPACE_ROOT_DIR", "/workspace")


logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(funcName)s : %(message)s")


def make_node_online(jenkins_info):
    node = jenkins_info["node"]
    logging.info("trying to put node '{}' back online".format(node))
    server = jenkins.Jenkins(jenkins_info["url"], username=jenkins_info["user"], password=jenkins_info["pass"])
    server.get_version()
    server.enable_node(node)
    logging.info("node '{}'is now online".format(node))
    return True


def make_node_offline(jenkins_info):
    node = jenkins_info["node"]
    logging.info("checking node '{}' status".format(node))
    server = jenkins.Jenkins(jenkins_info["url"], username=jenkins_info["user"], password=jenkins_info["pass"])
    server.get_version()
    node_info = server.get_node_info(node)
    if node_info["idle"]:
        logging.info("node '{}' is currently idle, trying to put it offline".format(node))
        server.disable_node(node, msg="jenkins-worker-monitor: putting offline for cleanup")
        logging.info("node '{}' is now offline".format(node))
        return True
    else:
        logging.warning("node '{}' is currently not idle, cannot put it offline".format(node))
        return False


def cleanup_docker(docker_host_url, keep_images_until):
    logging.info("starting docker cleanup")
    docker_client = docker.DockerClient(base_url=docker_host_url, version="1.25")

    byts = docker_client.containers.prune()["SpaceReclaimed"]
    logging.info("cleaned up stopped/stale containers, space reclaimed: {} bytes".format(byts))

    byts = docker_client.volumes.prune()["SpaceReclaimed"]
    logging.info("cleaned up unused/dangling volumes, space reclaimed: {} bytes".format(byts))

    byts = docker_client.images.prune(filters={"dangling": False, "until": keep_images_until + "h"})["SpaceReclaimed"]
    logging.info("cleaned up all dangling images and unused images(older than {} hours), space reclaimed: {} bytes".format(until, byts))

    logging.info("finished docker cleanup")


def cleanup_workspace(workspace_root_dir):
    logging.info("starting workspace cleanup at '{}'".format(workspace_root_dir))
    shutil.rmtree(workspace_root_dir, ignore_errors=True)
    os.makedirs(workspace_root_dir, exist_ok=True)
    logging.info("finished workspace cleanup")


def check_disk_usage(path, threshold):
    total, used, available = shutil.disk_usage(path)
    used_perc = math.ceil(used / total * 100)

    critical = used_perc >= threshold
    if critical:
        logging.critical("disk usage of {}: ~{}% [threshold: {}%]".format(path, used_perc, threshold))
    else:
        logging.info("disk usage of {}: ~{}% [threshold: {}%]".format(path, used_perc, threshold))

    return critical
    

def main():
    docker_keep_images_until = os.getenv("KEEP_IMAGES_UNTIL", "72")
    threshold = int(os.getenv("DISK_THRESHOLD", "70"))
    minutes = int(os.getenv("CHECK_INTERVAL", "5"))
    jenkins_url = os.getenv("JENKINS_URL", "https://engci-private-sjc.cisco.com/jenkins/iotsp/")

    try:
        node_name = os.environ["NODE_NAME"]
        jenkins_user = os.environ["JENKINS_USER"]
        jenkins_pass = os.environ["JENKINS_PASS"]
    except KeyError as e:
        logging.error("environment variable {} not found".format(e))
        raise SystemExit

    jenkins_info = {
        "user": jenkins_user,
        "pass": jenkins_pass,
        "url": jenkins_url,
        "node": node_name
    }

    docker_host_url = "unix://docker.sock"
    docker_root_dir = "/docker"
    workspace_root_dir = "/workspace"

    while True:
        logging.info("***** checking disk usage *****")

        try:
            docker_usage_critical = check_disk_usage(docker_root_dir, threshold)
            workspace_usage_critical = check_disk_usage(workspace_root_dir, threshold)
            
            node_offline = False
            if docker_usage_critical or workspace_usage_critical:
                logging.info("starting cleanup operations")
                node_offline = make_node_offline(jenkins_info)

                if node_offline:
                    if docker_usage_critical:
                        cleanup_docker(docker_host_url, docker_keep_images_until)
                    if workspace_usage_critical:
                        cleanup_workspace(workspace_root_dir)

                    logging.info("disk usage after cleanup:")
                    check_disk_usage(docker_root_dir, threshold)
                    check_disk_usage(workspace_root_dir, threshold)
                    logging.info("finished all cleanup operations")
                else:
                    logging.warning("skipping cleanup")

        except Exception as e:
            logging.error(e)
        finally:
            if node_offline: make_node_online(jenkins_info)

        logging.info("***** checking again after {} minute(s) *****".format(minutes))
        time.sleep(minutes * 60)


if __name__ == "__main__":
    main()

