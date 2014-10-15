#!/bin/bash

pushd `dirname $0` > /dev/null
SCRIPTPATH=`pwd`
popd > /dev/null

SCRIPTPATH=${SCRIPTPATH}'/../'

pushd ${SCRIPTPATH}

coverage erase
nosetests --with-coverage --cover-html --cover-tests

popd
