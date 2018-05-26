#!/usr/bin/python3


import os
import math
import docker
import jenkins
import shutil
import time
import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(message)s")


def make_node_online(jenkins_info):
    node = jenkins_info["node"]
    logging.info("trying to put node '{}' back online".format(node))
    logging.info("connecting to jenkins server")
    server = jenkins.Jenkins(jenkins_info["url"], username=jenkins_info["user"], password=jenkins_info["pass"])
    server.get_version()
    server.enable_node(node)
    logging.info("node '{}'is now online".format(node))
    return True


def make_node_offline(jenkins_info):
    node = jenkins_info["node"]
    logging.info("checking node '{}' status".format(node))
    logging.info("connecting to jenkins server")
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
    docker_client = docker.DockerClient(build_url=docker_host_url)

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
    jenkins_url = os.getenv("JENKINS_URL", "https://engci-private-sjc.cisco.com/jenkins/iotsp/"),

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

    try:
        while True:
            logging.info("***** checking disk usage *****")
            docker_usage_critical = check_disk_usage(docker_root_dir, threshold)
            workspace_usage_critical = check_disk_usage(workspace_root_dir, threshold)
            
            if docker_usage_critical or workspace_usage_critical:
                logging.info("starting cleanup operations")
                offline = make_node_offline(jenkins_info)

                if offline:
                    if docker_usage_critical:
                        cleanup_docker(docker_host_url, docker_keep_images_until)
                    if workspace_usage_critical:
                        cleanup_workspace(workspace_root_dir)

                    logging.info("disk usage after cleanup:")
                    check_disk_usage(docker_root_dir, threshold)
                    check_disk_usage(workspace_root_dir, threshold)
                    logging.info("finished all cleanup operations")
                    make_node_online(jenkins_info)
                else:
                    logging.warning("skipping cleanup")

            logging.info("***** checking again after {} minute(s) *****".format(minutes))
            time.sleep(minutes * 60)
    except KeyboardInterrupt:
        logging.info("stopping")
    except Exception as e:
        logging.error(e)


if __name__ == "__main__":
    main()

