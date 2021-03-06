#!/bin/bash

# Ta very much: https://github.com/fmahnke/shell-semver/blob/master/increment_version.sh
# Parse command line options.
while getopts ":Mmp" Option
do
  case $Option in
    M ) major=true;;
    m ) minor=true;;
    p ) patch=true;;
  esac
done

if [[ $major == "" && $minor == "" && $patch == ""  ]]; then
  echo "Usage: release.sh -Mmp"
  exit 1
fi

shift $(($OPTIND - 1))
version=$(git describe --tags `git rev-list --tags --max-count=1`)

# Build array from version string.
a=( ${version//./ } )

# If version string is missing or has the wrong number of members, show usage message.
if [ ${#a[@]} -ne 3 ]
then
  echo "usage: $(basename $0) [-Mmp] major.minor.patch"
  exit 1
fi

# Increment version numbers as requested.
if [ ! -z $major ]
then
  ((a[0]++))
  a[1]=0
  a[2]=0
fi

if [ ! -z $minor ]
then
  ((a[1]++))
  a[2]=0
fi

if [ ! -z $patch ]
then
  ((a[2]++))
fi

new_version="${a[0]}.${a[1]}.${a[2]}"

git tag -s $new_version
git push origin $new_version
