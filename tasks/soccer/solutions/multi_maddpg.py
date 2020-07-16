import os
from os.path import join
import pickle
import numpy as np
import torch.optim as optim
import torch
from torch import nn
from torch.nn import functional as F
from tools.rl_constants import Experience, Brain, BrainSet
from tasks.soccer.solutions.utils import STRIKER_STATE_SIZE, GOALIE_STATE_SIZE, NUM_STRIKER_AGENTS,\
    NUM_GOALIE_AGENTS, get_simulator, GOALIE_BRAIN_NAME, STRIKER_BRAIN_NAME, GOALIE_ACTION_SIZE, STRIKER_ACTION_SIZE, \
    GOALIE_ACTION_DISCRETE_RANGE, STRIKER_ACTION_DISCRETE_RANGE
from agents.maddpg_agent import MADDPGAgent
from tasks.tennis.solutions.maddpg import SOLUTIONS_CHECKPOINT_DIR
from agents.policies.maddpg_policy import MADDPGPolicy
from tools.misc import LinearSchedule
from agents.models.components import noise as rm
# from tools.misc import *
from agents.memory.memory import Memory

SAVE_TAG = 'homogeneous_maddpg_baseline'
ACTOR_CHECKPOINT_FN = lambda brain_name: join(SOLUTIONS_CHECKPOINT_DIR, f'{brain_name}_{SAVE_TAG}_actor_checkpoint.pth')
CRITIC_CHECKPOINT_FN = lambda brain_name: join(SOLUTIONS_CHECKPOINT_DIR, f'{brain_name}_{SAVE_TAG}_critic_checkpoint.pth')
TRAINING_SCORES_SAVE_PATH_FN = lambda brain_name: join(SOLUTIONS_CHECKPOINT_DIR, f'{brain_name}_{SAVE_TAG}_training_scores.pkl')


NUM_EPISODES = 1000
MAX_T = 1000
SOLVE_SCORE = 2
WARMUP_STEPS = 1#5000
BUFFER_SIZE = int(1e6)  # replay buffer size
ACTOR_LR = 1e-3  # Actor network learning rate
CRITIC_LR = 1e-4  # Actor network learning rate
SEED = 0


class Critic(nn.Module):
    """Actor (Policy) Model."""

    def __init__(self, state_size, action_size, num_agents, fc1, fc2, seed):
        """Initialize parameters and build model.
        Params
        ======
            state_size (int): Dimension of each state
            action_size (int): Dimension of each action
            seed (int): Random seed
        """
        super(Critic, self).__init__()
        self.seed = torch.manual_seed(seed)
        input_dim = state_size * num_agents + action_size
        self.fc1 = nn.Linear(input_dim, fc1)
        self.fc2 = nn.Linear(fc1 + action_size, fc2)

        self.bn = nn.BatchNorm1d(input_dim)
        self.bn2 = nn.BatchNorm1d(fc1)

        self.fc5 = nn.Linear(fc2, 1)

        # last layer weight and bias initialization
        self.fc5.weight.data.uniform_(-3e-4, 3e-4)
        self.fc5.bias.data.uniform_(-3e-4, 3e-4)

        # torch.nn.init.uniform_(self.fc5.weight, a=-3e-4, b=3e-4)
        # torch.nn.init.uniform_(self.fc5.bias, a=-3e-4, b=3e-4)

    def forward(self, input_, action):
        """Build a network that maps state & action to action values."""
        action = action.float()
        # print("input_.shape: {}".format(input_.shape))
        x = self.bn(input_)
        # print("x.shape: {}".format(x.shape))

        x = self.fc1(x)
        # print("x2.shape: {}".format(x.shape))

        x = F.relu(self.bn2(x))

        x = torch.cat([x, action], dim=1)
        x = F.relu(self.fc2(x))

        x = self.fc5(x)
        return x


class Actor(nn.Module):

    def __init__(self, state_size, action_size, fc1, fc2, seed, with_argmax: bool = False):
        super(Actor, self).__init__()

        # network mapping state to action

        self.seed = torch.manual_seed(seed)

        self.bn = nn.BatchNorm1d(state_size)
        self.bn2 = nn.BatchNorm1d(fc1)
        self.bn3 = nn.BatchNorm1d(fc2)

        self.fc1 = nn.Linear(state_size, fc1)
        self.fc2 = nn.Linear(fc1, fc2)
        self.fc4 = nn.Linear(fc2, action_size)

        # last layer weight and bias initialization
        torch.nn.init.uniform_(self.fc4.weight, a=-3e-3, b=3e-3)
        torch.nn.init.uniform_(self.fc4.bias, a=-3e-3, b=3e-3)

        # Tanh
        self.tan = nn.Tanh()
        self.with_argmax = with_argmax
        self.softmax = torch.nn.Softmax(dim=-1)

    def forward(self, x: torch.Tensor):
        if isinstance(x, torch.Tensor):
            if x.dim() == 1:
                x = x.unsqueeze(0)
        x = self.bn(x)
        x = F.relu(self.bn2(self.fc1(x)))
        x = F.relu(self.bn3(self.fc2(x)))
        x = (self.fc4(x))

        norm = torch.norm(x)

        # h3 is a 2D vector (a force that is applied to the agent)
        # we bound the norm of the vector to be between 0 and 10

        x = 10.0 * (F.tanh(norm)) * x / norm if norm > 0 else 10 * x

        if self.with_argmax:
            x = self.softmax(x)
            x = x.max(1, keepdim=True)[1]
        return x


def step_agents_fn(brain_set: BrainSet, next_brain_environment: dict, t: int):
    import time
    t1 = time.time()
    for brain_name, brain_environment in next_brain_environment.items():
        num_agents = brain_set[brain_name].num_agents
        for agent_number in range(num_agents):
            i = agent_number
            joint_state = torch.cat((brain_environment['states'][i], *[brain_environment['states'][j] for j in range(num_agents) if j != i]))
            joint_action = np.concatenate((brain_environment['actions'][i], *[brain_environment['actions'][j] for j in range(num_agents) if j != i]))
            join_next_state = torch.cat((brain_environment['next_states'][i], *[brain_environment['next_states'][j] for j in range(num_agents) if j != i]))

            # print("join_next_state shape: {}".format(join_next_state.shape))
            brain_agent_experience = Experience(
                state=brain_environment['states'][agent_number],
                action=brain_environment['actions'][agent_number],
                reward=brain_environment['rewards'][agent_number],
                next_state=brain_environment['next_states'][agent_number],
                done=brain_environment['dones'][agent_number],
                t_step=t,
                joint_state=joint_state,
                joint_action=torch.from_numpy(joint_action),
                joint_next_state=join_next_state
            )
            brain_set[brain_name].agent.step(brain_agent_experience, agent_number=agent_number)
    t2 = time.time()
    print(t2-t1)


if __name__ == '__main__':
    simulator = get_simulator()

    goalie_maddpg_agent = MADDPGAgent(
        policy=MADDPGPolicy(
            noise_factory=lambda: rm.OrnsteinUhlenbeckProcess(size=(GOALIE_ACTION_SIZE,), std=LinearSchedule(0.4, 0, 2000)),
            action_dim=GOALIE_ACTION_SIZE,
            num_agents=NUM_GOALIE_AGENTS,
            continuous_actions=False,
            discrete_action_range=GOALIE_ACTION_DISCRETE_RANGE
        ),
        state_shape=GOALIE_STATE_SIZE,
        action_size=GOALIE_ACTION_SIZE,
        num_agents=NUM_GOALIE_AGENTS,
        critic_factory=lambda: Critic(GOALIE_STATE_SIZE, GOALIE_ACTION_SIZE, NUM_GOALIE_AGENTS, 400, 300, seed=SEED),
        actor_factory=lambda: Actor(GOALIE_STATE_SIZE, 3, 400, 300, seed=SEED, with_argmax=True),
        critic_optimizer_factory=lambda parameters: optim.Adam(parameters, lr=CRITIC_LR, weight_decay=1.e-5),
        actor_optimizer_factory=lambda parameters: optim.Adam(parameters, lr=ACTOR_LR),
        memory_factory=lambda: Memory(buffer_size=BUFFER_SIZE, seed=SEED),
        seed=0,
    )

    goalie_brain = Brain(
        brain_name=GOALIE_BRAIN_NAME,
        action_size=GOALIE_ACTION_SIZE,
        state_shape=GOALIE_STATE_SIZE,
        observation_type='vector',
        agent=goalie_maddpg_agent,
        num_agents=NUM_GOALIE_AGENTS,
    )

    striker_maddpg_agent = MADDPGAgent(
        policy=MADDPGPolicy(
            noise_factory=lambda: rm.OrnsteinUhlenbeckProcess(size=(STRIKER_ACTION_SIZE,), std=LinearSchedule(0.4, 0, 2000)),
            action_dim=STRIKER_ACTION_SIZE,
            num_agents=NUM_STRIKER_AGENTS,
            continuous_actions=False,
            discrete_action_range=STRIKER_ACTION_DISCRETE_RANGE
        ),
        state_shape=STRIKER_STATE_SIZE,
        action_size=STRIKER_ACTION_SIZE,
        num_agents=NUM_STRIKER_AGENTS,
        critic_factory=lambda: Critic(STRIKER_STATE_SIZE, STRIKER_ACTION_SIZE, NUM_STRIKER_AGENTS, 400, 300, seed=SEED),
        actor_factory=lambda: Actor(STRIKER_STATE_SIZE, 5, 400, 300, seed=SEED, with_argmax=True),
        critic_optimizer_factory=lambda parameters: optim.Adam(parameters, lr=CRITIC_LR, weight_decay=1.e-5),
        actor_optimizer_factory=lambda parameters: optim.Adam(parameters, lr=ACTOR_LR),
        memory_factory=lambda: Memory(buffer_size=BUFFER_SIZE, seed=SEED),
        seed=0,
    )

    striker_brain = Brain(
        brain_name=STRIKER_BRAIN_NAME,
        action_size=STRIKER_ACTION_SIZE,
        state_shape=STRIKER_STATE_SIZE,
        observation_type='vector',
        agent=striker_maddpg_agent,
        num_agents=NUM_STRIKER_AGENTS
    )

    brain_set = BrainSet(brains=[goalie_brain, striker_brain])

    simulator.warmup(brain_set, step_agents_fn=step_agents_fn, n_episodes=int(WARMUP_STEPS / MAX_T), max_t=MAX_T)

    brain_set, training_scores, i_episode, training_time = simulator.train(
        brain_set,
        n_episodes=NUM_EPISODES,
        max_t=MAX_T,
        solved_score=SOLVE_SCORE,
        step_agents_fn=step_agents_fn,
        reward_accumulation_fn=lambda rewards: np.max(rewards),
    )

    if training_scores.get_mean_sliding_scores() > SOLVE_SCORE:
        for brain_name, brain in brain_set:
            trained_agent = brain.agent
            torch.save(trained_agent.online_actor.state_dict(), ACTOR_CHECKPOINT_FN(brain_name))
            torch.save(trained_agent.online_critic.state_dict(), CRITIC_CHECKPOINT_FN(brain_name))
            with open(TRAINING_SCORES_SAVE_PATH_FN(brain_name), 'wb') as f:
                pickle.dump(training_scores, f)
