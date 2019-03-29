'''
    Dynamic Movement Primitive Class
    Author: Michail Theofanidis, Joe Cloud, James Brady
'''

import numpy as np
from pyrdmp.utils import psi
import matplotlib.pyplot as plt

class DynamicMovementPrimitive:

    """Create an DMP.
        
        Keyword arguments:
        a -- Gain a of the transformation system
        b -- Gain b of the transformation system
        as_deg -- Degradation of the canonical system
        ng -- Number of Gaussian
        stb -- Stabilization term
        obs -- use obstacle avoidance term
    """

    def __init__(self, _a, _ng, _stb, _obs=False, _obs_gamma=1200, _obs_beta=6.3662):
       
        self.a = _a
        self.b = _a/4
        self.as_deg = _a/3
        self.ng = _ng
        self.stb = _stb
        self.obs = _obs
        self.obs_gamma = _obs_gamma
        self.obs_beta = _obs_beta

    # Create the phase of the system using the time vector
    def phase(self, time):
        return np.exp((-self.as_deg) * np.linspace(0, 1.0, len(time))).T

    # Generate a gaussian distribution
    def distributions(self, s, h=1):

        # Find the centers of the Gaussian in the s domain
        c = np.linspace(min(s), max(s), self.ng)
        d = c[1] - c[0]
        c /= d
        # Calculate every gaussian
        psv = np.array([[psi(h, _c, _s/d) for _s in s] for _c in c]) 

        return psv

    # Imitation Learning
    def imitate(self, x, dx, ddx, time, s, psv):

        # Initialize variables
        sigma = np.zeros((len(time)))  
        if x.ndim > 1:
            f_target = np.zeros((len(time),len(x[0]))) 
        else:
            f_target = np.zeros((len(time)))

        g = x[-1]
        x0 = x[0]
        tau = time[-1]

        # Compute ftarget
        for i in range(0, len(time)):

            # Add stabilization term
            if self.stb:
                mod = self.b*(g - x0)*s[i]
                sigma[i] = (g - x0)*s[i]
            else:
                mod = 0
                sigma[i] = s[i]
            
            # Check again in the future
            f_target[i] = np.power(tau, 2)*ddx[i] - self.a*(self.b*(g - x[i]) - tau*dx[i]) + mod

        # Regression
        w = [sigma.T.dot(np.diag(p)).dot(f_target)/(sigma.T.dot(np.diag(p)).dot(sigma)) for p in psv]

        return f_target, np.array(w)

    def avoid_obstacles(self,  x, dx, g, obstacles):
        p = np.zeros(x.shape)
        
        for o in obstacles[:,:3]:
            if np.linalg.norm(dx) > 0.00005:
                phi = np.arccos(np.dot(dx, o - x)/(np.linalg.norm(o - x)*np.linalg.norm(dx)))
                if np.dot(dx, o - x) < 0: #BUG: This is 3d. 
                    phi = -phi
            	
                dphi = self.obs_gamma * phi * np.exp(-self.obs_beta * abs(phi))
            	if np.linalg.norm(o - x) > np.linalg.norm(g - x):
            	    dphi = 0
 
            	p += dphi
        return p


    # Geeerate a trajectory
    def generate(self, w, x0, g, time, s, psv, obstacles = []):

        # Initialize variables
        sigma = np.zeros(len(time))
        if w.ndim > 1:
            ddx, dx, x, f_rep = np.zeros((4, len(time), len(w[0])))
        else:
            ddx, dx, x, f_rep = np.zeros((4, len(time)))
        tau = time[-1]
        dx_r = 0
        x_r = x0
        p = 0

        for i in range(len(time)):

            p_sum = 0
            p_div = 0

            if i == 0:
                dt = time[i]
            else:
                dt = time[i] - time[i - 1]

            # Add stabilization term
            if self.stb:
                mod = self.b*(g - x0)*s[i]
                sigma[i] = (g - x0)*s[i]
            else:
                mod = 0
                sigma[i] = s[i]

            for j in range(self.ng):

                p_sum += psv[j][i]*w[j]
                p_div += psv[j][i]

            # Calculate the new control input
            f_rep[i] = p_sum/p_div*sigma[i]

            if self.obs:
                p = self.avoid_obstacles(x[i-1], dx[i-1], g, obstacles)

        
            # Calculate the new trajectory
            ddx_r = (self.a*(self.b*(g - x_r) - tau*dx_r) + f_rep[i] + mod + p)/np.power(tau, 2)
            dx_r += ddx_r*dt
            x_r += dx_r*dt

            ddx[i], dx[i], x[i] = ddx_r, dx_r, x_r

        return ddx, dx, x

    # Adaptation using reinforcement learning
    def adapt(self, w, x0, g, t, s, psv, samples, rate):

        print('Trajectory adapted')

        # Initialize the action variables
        a = w
        tau = t[-1]

        # Flag which acts as a stop condition
        met_threshold = False
        counter = 0
        gain = []

        while not met_threshold:
            exploration = np.array([[np.random.normal(0, np.std(psv[j]*a[j]))
                    for j in range(self.ng)] for i in range(samples)])

            actions = np.array([a + e for e in exploration])

            # Generate new rollouts
            ddx, dx, x = np.transpose([self.generate(act, x0, g, t, s, psv) for act in actions], (1, 2, 0))

            # Estimate the Q values
            Q = [sum([self.reward(g, x[j, i], t[j], tau) for j in range(len(t))]) for i in range(samples)]

            # Sample the highest Q values to adapt the action parameters
            sort_Q = np.argsort(Q)[::-1][:np.floor(samples*rate).astype(int)]

            # Update the action parameter
            sumQ_y = sum([Q[i] for i in sort_Q])
            sumQ_x = sum([exploration[i]*Q[i] for i in sort_Q])

            # Update the policy parameters
            a += sumQ_x/sumQ_y

            gain.append(Q[sort_Q[0]])

            # Stopping condition
            if np.abs(x[-1, sort_Q[0]] - g) < 0.01:
                met_threshold = True

        return ddx[:, sort_Q[0]], dx[:, sort_Q[0]], x[:, sort_Q[0]], actions[sort_Q[0]], np.cumsum(gain)

    # Reward function
    def reward(self, goal, position, time, tau, w=0.9, threshold=0.01):

        dist = goal - position

        if np.abs(time - tau) < threshold:
            rwd = w*np.exp(-np.sqrt(dist*dist.T))
        else:
            rwd = (1-w) * np.exp(-np.sqrt(dist*dist.T))/tau

        return rwd

