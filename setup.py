from setuptools import setup

setup(name='devpisync',
      version='0.1',
      description='tool to ensure you have all required packages in your devpi-server',
      url='http://github.com/vayw/devpisync',
      entry_points = {
          'console_scripts': ['devpisync=devpisync.main:main'],
      },
      author='Ivan Kirillov',
      author_email='vayw@botans.org',
      license='MIT',
      packages=['devpisync'],
      zip_safe=False)
